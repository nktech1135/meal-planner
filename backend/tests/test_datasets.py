import hashlib
import io
import json
import zipfile

import httpx
import pytest

from app.main import app
from app.models import CookingYield, Food, ImportJob, RetentionProfile
from app.routers.admin import run_in_thread
from app.services import datasets
from tests.conftest import register


def fdc_food(fdc_id, name, protein, category="Poultry Products", data_type="SR Legacy", water=70.0):
    return {"fdcId": fdc_id, "description": name, "dataType": data_type, "foodCategory": {"description": category},
            "foodNutrients": [
                {"nutrient": {"number": "203", "unitName": "g"}, "amount": protein,
                 "foodNutrientDerivation": {"description": "Analytical"}},
                {"nutrient": {"number": "208", "unitName": "kcal"}, "amount": protein * 5},
                {"nutrient": {"number": "255", "unitName": "g"}, "amount": water},
            ],
            "foodPortions": [{"amount": 1, "measureUnit": {"name": "cup"}, "modifier": "", "gramWeight": 140}]}


SR_FOODS = [
    fdc_food(1, "Chicken, breast, meat only, raw", 22.5),
    fdc_food(2, "Chicken, breast, meat only, cooked, roasted", 31.0),
    fdc_food(3, "Chicken, breast, meat and skin, cooked, fried, batter", 24.0),  # no raw twin
    fdc_food(4, "Rice, white, long-grain, raw, enriched", 7.1, "Cereal Grains and Pasta"),
    fdc_food(5, "Rice, white, long-grain, enriched, cooked, without salt", 2.7, "Cereal Grains and Pasta"),
    fdc_food(6, "Fish, salmon, raw", 20.0, "Finfish and Shellfish Products"),
    fdc_food(7, "Fish, salmon, cooked, fried", 15.0, "Finfish and Shellfish Products"),  # would be >1: rejected
]
RETENTION_CSV = (
    "Retn_Code,FdGrp_CD,RetnDesc,Nutr_No,NutrDesc,Retn_Factor,Date\n"
    '1000,5,"CHICKEN,ROASTED",401,"Vitamin C",80,Sep-75\n'
    '1000,5,"CHICKEN,ROASTED",404,"Thiamin",75,Sep-75\n'
    '1000,5,"CHICKEN,ROASTED",417,"Folate, total",70,Sep-75\n'
    '5005,14,"ALC BEV,STIRRED",301,"Calcium, Ca",Sep-75,\n'
)


def make_zip(root: str, foods: list) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("data.json", json.dumps({root: foods}))
    return buf.getvalue()


@pytest.fixture
def fake_usda(monkeypatch):
    files = {"FoodData_Central_sr_legacy_food_json_2018-04.zip": make_zip("SRLegacyFoods", SR_FOODS)}
    csv_bytes = RETENTION_CSV.encode()
    monkeypatch.setattr(datasets, "DATASETS", tuple(
        datasets.Dataset(**{**d.__dict__, "sha256": hashlib.sha256(csv_bytes).hexdigest()}) if d.key == "usda_retention"
        else d for d in datasets.DATASETS))
    monkeypatch.setattr(datasets, "BY_KEY", {d.key: d for d in datasets.DATASETS})
    datasets._discovered.clear()

    def handler(req: httpx.Request):
        if req.url.path.endswith("download-datasets/"):
            return httpx.Response(200, text=" ".join(files))
        if "figshare" in req.url.host:
            return httpx.Response(200, content=csv_bytes)
        name = req.url.path.rsplit("/", 1)[-1]
        return httpx.Response(200, content=files[name]) if name in files else httpx.Response(404)

    client = httpx.Client(transport=httpx.MockTransport(handler))
    monkeypatch.setattr("app.routers.admin.http_client", lambda: client)
    app.dependency_overrides[run_in_thread] = lambda: (lambda fn: fn())  # run imports inline
    yield files
    if datasets._job_running.locked():  # a test that left its job queued, never run
        datasets._job_running.release()


def test_import_sr_legacy_and_derive_yields(user_client, db_session, fake_usda):
    job = user_client.post("/api/admin/datasets/fdc_sr_legacy/import").json()
    db_session.expire_all()
    job = db_session.get(ImportJob, job["id"])
    assert job.status == "done", job.message
    assert job.release == "2018-04"
    food = db_session.query(Food).filter_by(source="usda_fdc", source_id="1").one()
    assert food.trust_level == "analytical" and food.category == "Poultry Products"
    assert food.source_payload is None and "2018-04 release" in food.citation
    yields = {(y.raw_food.source_id, y.cooked_food.source_id): y for y in db_session.query(CookingYield)}
    assert set(yields) == {("1", "2"), ("4", "5")}  # batter-fried has no twin; salmon >1 rejected
    assert yields[("1", "2")].yield_factor == pytest.approx(22.5 / 31.0, abs=1e-4)
    assert yields[("4", "5")].method == "cooked"
    # Re-importing is idempotent.
    user_client.post("/api/admin/datasets/fdc_sr_legacy/import")
    assert db_session.query(Food).filter_by(source="usda_fdc").count() == len(SR_FOODS)
    assert db_session.query(CookingYield).count() == 2

    listing = {d["key"]: d for d in user_client.get("/api/admin/datasets").json()}
    assert listing["fdc_sr_legacy"]["records"] == len(SR_FOODS)
    assert listing["fdc_sr_legacy"]["imported_release"] == "2018-04"
    assert listing["fdc_sr_legacy"]["update_available"] is False


def test_logging_by_cooked_weight_uses_the_cooked_entry(user_client, db_session, fake_usda):
    user_client.post("/api/admin/datasets/fdc_sr_legacy/import")
    raw = db_session.query(Food).filter_by(source_id="1").one()
    y = db_session.query(CookingYield).filter_by(raw_food_id=raw.id).one()
    entry = user_client.post("/api/log", json={"food_id": raw.id, "quantity": 100, "weighed_state": "cooked",
                                               "yield_id": y.id, "meal": "dinner"}).json()
    assert entry["nutrients"]["protein_g"] == pytest.approx(31.0)  # the cooked entry's analysed value
    assert any("cooked entry" in n for n in entry["calc_notes"])
    assert entry["trust_level"] == "analytical"


def test_retention_import_and_use(user_client, db_session, fake_usda):
    job = user_client.post("/api/admin/datasets/usda_retention/import").json()
    db_session.expire_all()
    job = db_session.get(ImportJob, job["id"])
    assert job.status == "done" and "skipped 1" in job.message
    prof = db_session.get(RetentionProfile, 1000)
    assert prof.factors == {"vitamin_c_mg": 0.8, "thiamin_mg": 0.75, "folate_ug_dfe": 0.7}
    food = user_client.post("/api/foods", json={"name": "Chicken thigh, raw", "state": "raw",
                                                "nutrients": {"vitamin_c_mg": 10, "protein_g": 20}}).json()
    y = user_client.post("/api/yields", json={"raw_food_id": food["id"], "method": "roasted", "yield_factor": 0.75,
                                              "retention_profile_code": 1000}).json()
    assert y["retention"]["vitamin_c_mg"] == 0.8 and "CHICKEN,ROASTED" in y["citation"]
    entry = user_client.post("/api/log", json={"food_id": food["id"], "quantity": 75, "weighed_state": "cooked",
                                               "yield_id": y["id"]}).json()
    assert entry["nutrients"]["vitamin_c_mg"] == pytest.approx(8.0)  # 100 g raw × 10 mg × 0.8
    profiles = user_client.get("/api/retention-profiles", params={"q": "chicken"}).json()["profiles"]
    assert [p["code"] for p in profiles] == [1000]


def test_bad_checksum_fails_the_job(user_client, db_session, fake_usda, monkeypatch):
    monkeypatch.setattr(datasets, "BY_KEY", {**datasets.BY_KEY, "usda_retention": datasets.Dataset(
        **{**datasets.BY_KEY["usda_retention"].__dict__, "sha256": "0" * 64})})
    job = user_client.post("/api/admin/datasets/usda_retention/import").json()
    db_session.expire_all()
    job = db_session.get(ImportJob, job["id"])
    assert job.status == "failed" and "Checksum mismatch" in job.message


def test_only_one_import_at_a_time_and_admin_only(client, db_session, fake_usda):
    register(client, "admin@example.com")
    app.dependency_overrides[run_in_thread] = lambda: (lambda fn: None)  # leave the job queued
    assert client.post("/api/admin/datasets/fdc_sr_legacy/import").status_code == 202
    assert client.post("/api/admin/datasets/usda_retention/import").status_code == 409
    client.cookies.clear()
    register(client, "user@example.com")
    assert client.get("/api/admin/datasets").status_code == 403


def test_search_ranking(user_client, db_session, fake_usda):
    user_client.post("/api/admin/datasets/fdc_sr_legacy/import")
    user_client.post("/api/foods", json={"name": "My chicken stir fry", "nutrients": {}})
    names = [f["name"] for f in user_client.get("/api/foods", params={"q": "chicken"}).json()]
    assert names[0] == "My chicken stir fry"  # your own foods first
    assert names[1] == "Chicken, breast, meat only, raw"  # then shortest name starting with the query


def test_hidden_sources_filter_search(user_client, db_session):
    from app.sources.base import ExternalFood
    from app.sources.registry import bulk_upsert_external_foods

    def food(source, sid, name):
        return ExternalFood(source=source, source_id=sid, name=name, trust_level="analytical",
                            nutrients={"energy_kcal": (52.0, None)})
    bulk_upsert_external_foods(db_session, [food("ciqual", "1", "Apple, raw (FR)")])
    bulk_upsert_external_foods(db_session, [food("afcd", "F1", "Apple, raw (AU)")])
    db_session.commit()
    names = lambda: sorted(f["name"] for f in user_client.get("/api/foods", params={"q": "apple"}).json())  # noqa: E731
    assert names() == ["Apple, raw (AU)", "Apple, raw (FR)"]
    profile = user_client.get("/api/profile").json()
    user_client.put("/api/profile", json={**profile, "hidden_sources": ["ciqual"]})
    assert names() == ["Apple, raw (AU)"]


def test_food_database_credits(user_client, db_session):
    rows = {r["source"]: r for r in user_client.get("/api/datasets").json()}
    assert rows["usda_fdc"]["country"] == "United States"
    assert rows["cofid"]["licence"] == "Open Government Licence v3.0"
    assert "Open Government Licence – Canada" in rows["cnf"]["attribution"]
    assert all(r["records"] == 0 for r in rows.values())


def test_parsed_import_keeps_extensions_and_skips_optional_files(user_client, db_session, monkeypatch):
    """The real AFCD workbooks go through the job: names keep '.xlsx' (openpyxl needs it)."""
    from pathlib import Path

    fixtures = Path(__file__).parent / "fixtures" / "intl" / "afcd"
    ds = datasets.BY_KEY["intl_afcd"]
    files = tuple(datasets.RemoteFile(f.name, f.url) for f in ds.files) + (
        datasets.RemoteFile("extra", "https://example.org/missing.json", optional=True),)
    monkeypatch.setitem(datasets.BY_KEY, "intl_afcd", datasets.Dataset(**{**ds.__dict__, "files": files}))
    content = {"Nutrient%20profiles": (fixtures / "profiles.xlsx").read_bytes(),
               "Food%20Details": (fixtures / "details.xlsx").read_bytes()}

    def handler(req):
        hit = next((v for k, v in content.items() if k in str(req.url)), None)
        return httpx.Response(200, content=hit) if hit else httpx.Response(404)

    monkeypatch.setattr("app.routers.admin.http_client", lambda: httpx.Client(transport=httpx.MockTransport(handler)))
    app.dependency_overrides[run_in_thread] = lambda: (lambda fn: fn())
    job = user_client.post("/api/admin/datasets/intl_afcd/import").json()
    db_session.expire_all()
    job = db_session.get(ImportJob, job["id"])
    assert job.status == "done", job.message
    assert db_session.query(Food).filter_by(source="afcd").count() == 5


def test_search_prefers_the_users_database_and_folds_plurals(user_client, db_session):
    from app.sources.base import ExternalFood
    from app.sources.registry import bulk_upsert_external_foods

    def food(source, sid, name):
        return ExternalFood(source=source, source_id=sid, name=name, trust_level="analytical", data_type="SR Legacy",
                            nutrients={"energy_kcal": (52.0, None)})
    bulk_upsert_external_foods(db_session, [food("bls", "F1", "Apple raw")])
    bulk_upsert_external_foods(db_session, [food("usda_fdc", "171688", "Apples, raw, with skin")])
    bulk_upsert_external_foods(db_session, [food("cofid", "14-319", "Apples, eating, raw, flesh and skin")])
    db_session.commit()
    first = lambda: user_client.get("/api/foods", params={"q": "apple raw"}).json()[0]["name"]  # noqa: E731
    assert first() == "Apples, raw, with skin"  # USDA by default, despite the plural
    profile = user_client.get("/api/profile").json()
    user_client.put("/api/profile", json={**profile, "preferred_source": "cofid"})
    assert first() == "Apples, eating, raw, flesh and skin"


def _run_inline(monkeypatch, client=None):
    monkeypatch.setattr("app.routers.admin.http_client",
                        lambda: client or httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(404))))
    app.dependency_overrides[run_in_thread] = lambda: (lambda fn: fn())


def test_vendored_dataset_imports_offline_with_checksum(user_client, db_session, monkeypatch):
    _run_inline(monkeypatch)  # any network use would 404
    job = user_client.post("/api/admin/datasets/intl_fineli/import").json()
    db_session.expire_all()
    job = db_session.get(ImportJob, job["id"])
    assert job.status == "done", job.message
    assert db_session.query(Food).filter_by(source="fineli").count() == 4232


def test_assembled_dataset_records_publisher_version(user_client, db_session, monkeypatch):
    import json
    from pathlib import Path

    from app.sources.intl import se_livsmedel

    excerpt = json.loads((Path(__file__).parent / "fixtures" / "intl" / "se_livsmedel" / "livsmedel_excerpt.json").read_text())
    calls = []

    def fake_fetch_all(client, progress):
        calls.append(client)
        progress("Fetching foods…", 1, 2)
        return excerpt

    monkeypatch.setattr(se_livsmedel, "fetch_all", fake_fetch_all)
    _run_inline(monkeypatch)
    job = user_client.post("/api/admin/datasets/intl_se_livsmedel/import").json()
    db_session.expire_all()
    job = db_session.get(ImportJob, job["id"])
    assert job.status == "done", job.message
    assert len(calls) == 1
    assert job.release == excerpt["version"]
    assert db_session.query(Food).filter_by(source="se_livsmedel").count() == len(excerpt["foods"])
