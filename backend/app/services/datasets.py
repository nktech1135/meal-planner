"""Bulk reference datasets the admin can import from the UI.

- USDA FoodData Central Foundation, SR Legacy and Survey (FNDDS) foods: public domain
  JSON downloads, streamed so the largest (SR Legacy, ~210 MB of JSON) never sits in memory.
- USDA Table of Nutrient Retention Factors, Release 6 (2007): public domain CSV,
  pinned by checksum.

After a food import, cooking yields are derived for raw/cooked pairs (see ``derive_usda_yields``).
"""

import csv
import hashlib
import io
import logging
import re
import tempfile
import threading
import zipfile
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

import httpx
import ijson
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from app.models import CookingYield, Food, ImportJob, RetentionProfile
from app.nutrients import BY_FDC_NUMBER, Trust, weakest
from app.sources.registry import bulk_upsert_external_foods
from app.sources.usda_fdc import parse_fdc_food

log = logging.getLogger(__name__)

FDC_FILES = "https://fdc.nal.usda.gov/fdc-datasets/"
FDC_DOWNLOAD_PAGE = "https://fdc.nal.usda.gov/download-datasets/"
USER_AGENT = "mealplan (dataset import)"


@dataclass(frozen=True)
class Dataset:
    key: str
    label: str
    description: str
    size: str
    file_prefix: str | None = None  # FDC: discovered as <prefix><YYYY-MM[-DD]>.zip
    pinned_file: str | None = None
    root_key: str | None = None  # FDC: top-level JSON array
    url: str | None = None  # non-FDC: fixed URL
    sha256: str | None = None
    release: str | None = None


DATASETS = (
    Dataset("fdc_foundation", "USDA Foundation Foods",
            "Lab-analysed foods with detailed nutrient profiles; updated twice a year.", "~1 MB download",
            "FoodData_Central_foundation_food_json_", "FoodData_Central_foundation_food_json_2026-10-29.zip",
            "FoundationFoods"),
    Dataset("fdc_sr_legacy", "USDA SR Legacy",
            "About 7,800 foods, raw and cooked, from the final Standard Reference release (2018).", "~13 MB download",
            "FoodData_Central_sr_legacy_food_json_", "FoodData_Central_sr_legacy_food_json_2018-04.zip", "SRLegacyFoods"),
    Dataset("fdc_survey", "USDA Survey foods (FNDDS)",
            "About 5,400 foods and mixed dishes as eaten in the U.S. (What We Eat in America).", "~4 MB download",
            "FoodData_Central_survey_food_json_", "FoodData_Central_survey_food_json_2024-10-31.zip", "SurveyFoods"),
    Dataset("fdc_branded", "USDA Branded Foods",
            "About 430,000 U.S. packaged foods from manufacturer labels, with barcodes and ingredient lists. "
            "Takes a few minutes and about 1 GB of database space.", "~200 MB download (3 GB of data)",
            "FoodData_Central_branded_food_json_", "FoodData_Central_branded_food_json_2026-10-29.zip", "BrandedFoods"),
    Dataset("usda_retention", "USDA Nutrient Retention Factors (Release 6, 2007)",
            "How much of each vitamin and mineral survives a cooking method; used with cooking yields.",
            "~0.5 MB download", url="https://ndownloader.figshare.com/files/44488754",
            sha256="b863e891989020edf3a429af8060523e5dee275699ae08893a5f91ff9a84b1e5", release="Release 6 (2007)"),
)
BY_KEY = {d.key: d for d in DATASETS}

_discovered: dict[str, tuple[datetime, str]] = {}
BATCH = 1000  # foods per database round


def latest_file(ds: Dataset, client: httpx.Client) -> str:
    """The newest release file listed on FDC's download page (cached for a day), else the pinned one."""
    cached = _discovered.get(ds.key)
    if cached and datetime.now(UTC) - cached[0] < timedelta(days=1):
        return cached[1]
    name = ds.pinned_file
    try:
        page = client.get(FDC_DOWNLOAD_PAGE, headers={"User-Agent": USER_AGENT}, timeout=20).text
        found = re.findall(re.escape(ds.file_prefix) + r"(\d{4}-\d{2}(?:-\d{2})?)\.zip", page)
        if found:
            name = f"{ds.file_prefix}{max(found)}.zip"
    except httpx.HTTPError as exc:
        log.warning("Could not check FDC for new releases: %s", exc)
    _discovered[ds.key] = (datetime.now(UTC), name)
    return name


def release_of(file_name: str) -> str:
    match = re.search(r"(\d{4}-\d{2}(?:-\d{2})?)\.zip$", file_name)
    return match.group(1) if match else file_name


# --- Jobs ---------------------------------------------------------------------------

STALE_AFTER = timedelta(minutes=5)


def expire_stale_jobs(db: Session) -> None:
    """Jobs that stopped reporting (e.g. the server restarted mid-import) are marked failed."""
    cutoff = datetime.now(UTC) - STALE_AFTER
    for job in db.scalars(select(ImportJob).where(ImportJob.status.in_(("queued", "running")))):
        beat = job.heartbeat_at if job.heartbeat_at.tzinfo else job.heartbeat_at.replace(tzinfo=UTC)
        if beat < cutoff:
            job.status, job.finished_at = "failed", datetime.now(UTC)
            job.message = "Interrupted (the server stopped during the import)"
    db.commit()


def active_job(db: Session) -> ImportJob | None:
    expire_stale_jobs(db)
    return db.scalar(select(ImportJob).where(ImportJob.status.in_(("queued", "running"))))


def start_import(db: Session, dataset_key: str, user_id: int, client: httpx.Client,
                 run: Callable[[Callable[[], None]], None] | None = None) -> ImportJob:
    """Queue an import and run it in a background thread (``run`` lets tests run it inline)."""
    ds = BY_KEY[dataset_key]
    job = ImportJob(dataset=ds.key, created_by=user_id, message="Queued")
    db.add(job)
    db.commit()
    factory = sessionmaker(bind=db.get_bind(), autoflush=False, expire_on_commit=False)
    job_id = job.id

    def work():
        _run_job(factory, job_id, ds, client)

    (run or (lambda fn: threading.Thread(target=fn, name=f"import-{job_id}", daemon=True).start()))(work)
    return job


class _Progress:
    def __init__(self, db: Session, job: ImportJob):
        self.db, self.job = db, job

    def __call__(self, message: str, progress: int | None = None, total: int | None = None) -> None:
        if progress is not None:
            self.job.progress = progress
        if total is not None:
            self.job.total = total
        self.job.message = message
        self.job.heartbeat_at = datetime.now(UTC)
        self.db.commit()


def _run_job(factory: sessionmaker, job_id: int, ds: Dataset, client: httpx.Client) -> None:
    db = factory()
    job = db.get(ImportJob, job_id)
    report = _Progress(db, job)
    try:
        job.status = "running"
        report("Starting")
        if ds.root_key:
            _import_fdc(db, ds, client, job, report)
        else:
            _import_retention(db, ds, client, job, report)
        job.status, job.finished_at = "done", datetime.now(UTC)
        db.commit()
    except Exception as exc:  # a background job must record any failure rather than die silently
        log.exception("Import %s failed", ds.key)
        db.rollback()
        job = db.get(ImportJob, job_id)
        job.status, job.message, job.finished_at = "failed", f"Failed: {exc}", datetime.now(UTC)
        db.commit()
    finally:
        db.close()


def _download(client: httpx.Client, url: str, dest, report: _Progress) -> None:
    with client.stream("GET", url, headers={"User-Agent": USER_AGENT}, timeout=120, follow_redirects=True) as resp:
        resp.raise_for_status()
        size = int(resp.headers.get("content-length") or 0)
        done = 0
        for chunk in resp.iter_bytes(1 << 20):
            dest.write(chunk)
            done += len(chunk)
            report(f"Downloading… {done / 1e6:.1f}" + (f" of {size / 1e6:.1f} MB" if size else " MB"))
    dest.flush()


def _import_fdc(db: Session, ds: Dataset, client: httpx.Client, job: ImportJob, report: _Progress) -> None:
    file_name = latest_file(ds, client)
    job.release = release_of(file_name)
    with tempfile.TemporaryFile() as tmp:
        _download(client, FDC_FILES + file_name, tmp, report)
        tmp.seek(0)
        with zipfile.ZipFile(tmp) as zf:
            member = next((n for n in zf.namelist() if n.endswith(".json")), None)
            if member is None:
                raise ValueError("The download contains no JSON file")
            count, batch = 0, []
            with zf.open(member) as stream:
                for record in ijson.items(stream, f"{ds.root_key}.item", use_float=True):
                    batch.append(parse_fdc_food(record, release=job.release, keep_payload=False))
                    if len(batch) >= BATCH:
                        count += bulk_upsert_external_foods(db, batch)
                        batch = []
                        report(f"Imported {count:,} foods…", progress=count)  # commits the batch
                count += bulk_upsert_external_foods(db, batch)
            if count == 0:
                raise ValueError(f"No foods found under '{ds.root_key}' — has the file format changed?")
    report(f"Imported {count:,} foods; deriving cooking yields…", progress=count, total=count)
    pairs = derive_usda_yields(db)
    report(f"Imported {count:,} foods ({ds.label}, {job.release} release). {pairs:,} cooking yields from USDA "
           "raw/cooked pairs are now available.", progress=count, total=count)


# Nutrient numbers in the retention table that stand in for our canonical forms.
_RETENTION_ALIASES = {"417": "folate_ug_dfe", "318": "vitamin_a_ug"}  # total folate, vitamin A (IU)


def _import_retention(db: Session, ds: Dataset, client: httpx.Client, job: ImportJob, report: _Progress) -> None:
    job.release = ds.release
    buf = io.BytesIO()
    _download(client, ds.url, buf, report)
    data = buf.getvalue()
    if hashlib.sha256(data).hexdigest() != ds.sha256:
        raise ValueError("Checksum mismatch: the downloaded file is not the expected USDA release")
    profiles: dict[int, RetentionProfile] = {}
    skipped = 0
    for row in csv.DictReader(io.StringIO(data.decode("latin-1"))):
        try:
            percent = int(row["Retn_Factor"])
        except (TypeError, ValueError):
            skipped += 1  # a few source rows have no factor (the date sits in its column); never guess one
            continue
        code = int(row["Retn_Code"])
        prof = profiles.get(code)
        if prof is None:
            prof = profiles[code] = RetentionProfile(code=code, food_group=int(row["FdGrp_CD"]),
                                                     description=row["RetnDesc"].strip(), factors={}, release=ds.release)
        nutrient = BY_FDC_NUMBER.get(row["Nutr_No"])
        target = nutrient.code if nutrient else _RETENTION_ALIASES.get(row["Nutr_No"])
        if target and target not in prof.factors:
            prof.factors[target] = percent / 100
    for prof in profiles.values():
        db.merge(prof)
    db.commit()
    note = f"; skipped {skipped} source rows without a factor" if skipped else ""
    report(f"Imported {len(profiles)} retention profiles ({ds.release}){note}.", progress=len(profiles), total=len(profiles))


# --- Cooking yields from raw/cooked pairs ---------------------------------------------

COOKING_WORDS = {
    "cooked", "boiled", "roasted", "baked", "broiled", "grilled", "braised", "stewed", "steamed", "microwaved",
    "simmered", "fried", "pan-fried", "pan-broiled", "pan-browned", "dry heat", "moist heat", "toasted", "poached",
    "scrambled",
}
SHAPE_WORDS = {"patty", "crumbles", "loaf"}  # how ground meat was shaped for cooking
NEUTRAL_WORDS = {"without salt", "with salt", "without added salt", "with added salt", "drained", "drained solids"}
DRY_GOODS = {"Cereal Grains and Pasta", "Legumes and Legume Products"}  # sold "dry" rather than "raw"
GENERATED_BY = "usda-pairs"
MUSCLE_FOODS = {"Beef Products", "Pork Products", "Poultry Products", "Finfish and Shellfish Products",
                "Lamb, Veal, and Game Products", "Sausages and Luncheon Meats"}


def _parts(description: str) -> list[str]:
    description = re.sub(r"\([^)]*\)", "", description)  # e.g. "(Includes foods for USDA's Food Distribution Program)"
    return [p.strip().lower() for p in description.split(",") if p.strip()]


def derive_usda_yields(db: Session) -> int:
    """Create shared cooking yields for USDA foods whose raw and cooked entries differ only by preparation.

    Uses protein conservation (raw protein per 100 g ÷ cooked protein per 100 g); only for foods
    with at least 5 g protein per 100 g raw, where the estimate is stable, and only within the
    lab datasets (Survey/FNDDS dishes include coatings, oil and sauces, which breaks the pairing).
    Returns the number of derived yields now on file.
    """
    foods = list(db.scalars(select(Food).where(
        Food.source == "usda_fdc", Food.owner_id.is_(None),
        Food.source_data_type.in_(("Foundation", "SR Legacy")))))
    raws: dict[tuple, Food] = {}
    cooked: list[tuple[tuple, Food, list[str]]] = []
    for f in foods:
        parts = [p for p in _parts(f.name) if p not in NEUTRAL_WORDS and p not in SHAPE_WORDS]
        if f.state == "raw" or (f.state is None and "dry" in parts and f.category in DRY_GOODS):
            key = (f.category, tuple(p for p in parts if p not in ("raw", "dry")))
            raws.setdefault(key, f)
        elif f.state == "cooked":
            method = [p for p in parts if p in COOKING_WORDS]
            cooked.append(((f.category, tuple(p for p in parts if p not in COOKING_WORDS)), f, method))

    existing = {(y.raw_food_id, y.cooked_food_id): y for y in db.scalars(
        select(CookingYield).where(CookingYield.generated_by == GENERATED_BY))}
    kept: set[tuple[int, int]] = set()
    made = 0
    for key, cook, method_words in cooked:
        raw = raws.get(key)
        if raw is None:
            continue
        rp, cp = raw.nutrient_map().get("protein_g"), cook.nutrient_map().get("protein_g")
        if not rp or not cp or rp < 5:
            continue
        factor = rp / cp
        if not 0.3 <= factor <= 4 or (raw.category in MUSCLE_FOODS and factor > 1.0):
            continue  # implausible: meat and fish lose mass when cooked
        method = ", ".join(w for w in method_words if w != "cooked") or "cooked"
        y = existing.get((raw.id, cook.id))
        if y is None:
            y = CookingYield(raw_food_id=raw.id, cooked_food_id=cook.id, owner_id=None, generated_by=GENERATED_BY,
                             retention={}, basis="derived")
            db.add(y)
        y.method = method
        y.yield_factor = round(factor, 4)
        y.trust_level = weakest([raw.trust_level, cook.trust_level]) or Trust.USER
        y.citation = (f"Derived from USDA FoodData Central entries FDC {raw.source_id} (raw) and {cook.source_id} "
                      f"(cooked) by protein conservation.")
        y.notes = f"Logging by cooked weight uses the analysed nutrients of “{cook.name}”."
        kept.add((raw.id, cook.id))
        made += 1
    for pair, y in existing.items():
        if pair not in kept:
            db.delete(y)
    db.commit()
    return made
