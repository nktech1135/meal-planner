"""Swedish food composition database (Livsmedelsdatabasen, Swedish Food Agency / Livsmedelsverket), English.

The Food Agency publishes the database through a JSON API (CC BY 4.0) with one request per food for nutrient
values, and as an Excel export of the whole database from its search site (a POST, values only: no value
types, so below-detection-limit and logical zeros look alike). ``fetch_all`` assembles the import's ``data``
file from the API (the English names, EuroFIR codes and value types) plus the English Excel export (the food
groups and the database version, which the API lacks):

    {"version": "2026-07-01", "foods": [API food records], "nutrients": {"<nummer>": [nutrient values]},
     "groups": {"<nummer>": "Fruit, berry"}}

Definitions checked against the data (each value's ``metodindikator``, and the API's ``berakning`` formulas):

- Energy is published in kcal and kJ (EU Regulation 1169/2011 factors); kcal is used as published.
- CHO "Carbohydrates, available" (by difference, minus fibre) + FIBT "Fibre" (total dietary fibre) is ours.
- VITA is labelled "Retinol equivalents" (unit "RE/µg") but is RAE for almost all foods: its method is
  "Vitamin A activity calculated from retinol and beta-carotene (Factor 1/12)" or "... and other pro-vitamin A
  carotenoids (factor 1/12 and 1/24)" (Swedish: "Vitamin A aktivitet (RAE)"), or a recipe sum of those. It is
  used only with those methods (2 foods use "factor 1/6", i.e. RE; some give no method); otherwise RAE is
  derived from RETOL + CARTBTOT/12.
- VITE is alpha-tocopherol ("Vitamin E activity calculated as d-alpha-tocopherol"); VITD is D2 + D3 ("sum of
  ergocalciferol and cholecalciferol"). VITD_x (including 25-hydroxy-D3) is not mapped.
- NIA is preformed niacin; NIAEQ is not mapped. VITB6 is total vitamin B6.
- FOL is total folate, used as DFE with that caveat, except for foods likely to contain added folic acid:
  names saying "fortified"/vitamins added (but not cow's milk products and fat spreads, which Swedish
  fortification gives vitamins A and D only), "Nutrient supply" foods and infant formulas. Dishes made with
  fortified ingredients aren't detected (the API lists ingredients only per food).
- Not mapped: THIACLHCL (thiamin expressed as thiamin chloride hydrochloride, not thiamin), NACL (salt;
  sodium is mapped), free sugar.
- Value types: BL (below limit of detection), BQ (below limit of quantification) and TR (trace) are stored as
  0 with that reason; where a BL/BQ value carries a number it is the limit, recorded as "(<limit unit)". LZ
  (logical zero) is 0 with that note. N ("Unknown") values are left out.
"""

import io
import json
import re
import time
import zipfile
from collections.abc import Callable, Iterator
from pathlib import Path

import httpx

from app.sources.base import ExternalFood
from app.sources.intl.common import Components, make_food

SOURCE = "se_livsmedel"
DATA_TYPE = "Livsmedelsdatabasen"
ATTRIBUTION = "The Swedish Food Agency food database (Livsmedelsverket). Licensed under CC BY 4.0."
FOOD_URL = "https://soknaringsinnehall.livsmedelsverket.se/Home/FoodDetails/{nr}"
DERIVATION = "Livsmedelsdatabasen"
MAX_DERIVATION = 120

API = "https://dataportal.livsmedelsverket.se/livsmedel/api/v1"
EXPORT = "https://soknaringsinnehall.livsmedelsverket.se/Spara/HamtaHelaDatabasen"
ENGLISH_COOKIE = "SokNaringsinnehall.Sprak=Engelska"  # the export's language setting
USER_AGENT = "mealplan (dataset import)"
# Fields of a nutrient value the parser uses (the API sends ~20 per value).
VALUE_FIELDS = ("namn", "euroFIRkod", "varde", "enhet", "matrisenhetkod", "vardetypkod", "vardetyp", "metodtypkod",
                "metodindikator")
Progress = Callable[..., None]

# EuroFIR code -> our nutrient code or Components special key. Energy is split by unit below.
MAPPING: dict[str, str] = {
    "PROT": "protein_g", "FAT": "fat_g", "CHO": "available_carbs_g", "FIBT": "fiber_g", "SUGAR": "sugars_g",
    "SUGAD": "added_sugars_g", "FASAT": "sat_fat_g", "FAMS": "mono_fat_g", "FAPU": "poly_fat_g",
    "CHORL": "cholesterol_mg", "WATER": "water_g", "ALC": "alcohol_g",
    "NA": "sodium_mg", "K": "potassium_mg", "CA": "calcium_mg", "FE": "iron_mg", "MG": "magnesium_mg",
    "P": "phosphorus_mg", "ZN": "zinc_mg", "SE": "selenium_ug", "ID": "iodine_ug",
    "VITA": "vitamin_a_ug", "RETOL": "retinol_ug", "CARTBTOT": "beta_carotene_ug", "VITD": "vitamin_d_ug",
    "VITE": "vitamin_e_mg", "VITC": "vitamin_c_mg", "RIBF": "riboflavin_mg", "NIA": "niacin_mg",
    "VITB6": "vitamin_b6_mg", "VITB12": "vitamin_b12_ug", "FOL": "folate_ug_dfe",
}
SPECIAL_UNITS = {"available_carbs_g": "g", "retinol_ug": "µg", "beta_carotene_ug": "µg"}
ZERO_TYPES = {"BL": "below limit of detection", "BQ": "below limit of quantification", "TR": "trace",
              "LZ": "logical zero"}
RECIPE_METHOD = "ingredient level calculation procedure"
LIMIT_TYPES = {"BL", "BQ"}  # the published number, when not 0, is the limit
UNKNOWN_TYPES = {"N"}
FOLATE_CAVEAT = "total folate as DFE (no folic acid assumed)"
FOLIC_ACID_NAME = re.compile(r"fortified|folic|multivitamin|w/ vitamins|vitamins added|infant formula|follow-up formula",
                             re.IGNORECASE)
FOLIC_ACID_GROUPS = {"Nutrient supply"}
# Fortified with vitamins A and D only (Swedish practice for cow's milk products and spreads).
A_D_ONLY = re.compile(r"\b(milk|yoghurt|fermented milk|whey spread|margarine|blended spread|spread|fat blend|oil)\b",
                      re.IGNORECASE)
PLANT_BASED = re.compile(r"soy|oat|almond|substitute|non-dairy|plant|vegan|coconut|rice drink|w/o milk", re.IGNORECASE)
COOKING = {"boiled": ("cooked", "boiled"), "frying": ("cooked", "fried"), "cooked by dry heat": ("cooked", None),
           "cooked by heat": ("cooked", None)}


def attribution(version: str | None) -> str:
    """The Food Agency asks to be cited with the database version: 'The Swedish Food Agency food database,
    version 2026-07-01'."""
    if not version:
        return ATTRIBUTION
    return ATTRIBUTION.replace("(Livsmedelsverket).", f"(Livsmedelsverket), version {version}.")


# --- Fetching ----------------------------------------------------------------------------


def _get_json(client: httpx.Client, url: str, params: dict, attempts: int = 4):
    """GET with a few retries (with backoff) on network errors, 429 and 5xx."""
    for attempt in range(attempts):
        last = attempt == attempts - 1
        try:
            resp = client.get(url, params=params, timeout=60,
                              headers={"User-Agent": USER_AGENT, "Accept": "application/json"})
        except httpx.TransportError:
            if last:
                raise
        else:
            if resp.status_code != 429 and resp.status_code < 500 or last:
                resp.raise_for_status()
                return resp.json()
        time.sleep(2 * 2 ** attempt)
    raise AssertionError("unreachable")


def _export_groups(client: httpx.Client) -> tuple[str | None, dict[str, str]]:
    """(database version, food number -> English "Filter group") from the search site's Excel export."""
    import openpyxl  # noqa: PLC0415 - only needed here

    resp = client.post(EXPORT, headers={"User-Agent": USER_AGENT, "Cookie": ENGLISH_COOKIE}, timeout=120)
    resp.raise_for_status()
    sheet = openpyxl.load_workbook(io.BytesIO(resp.content), read_only=True).worksheets[0]
    version, header, groups = None, None, {}
    for row in sheet.iter_rows(values_only=True):
        if header is None:
            first = str(row[0] or "")
            if "version" in first:
                version = first.rsplit("version", 1)[1].strip() or None
            if first == "Food Name":
                header = [str(c or "") for c in row]
            continue
        cells = dict(zip(header, row, strict=False))
        if cells.get("Food Number") is not None and cells.get("Filter group"):
            groups[str(cells["Food Number"])] = str(cells["Filter group"]).strip()
    if header is None:
        raise ValueError("The Swedish Excel export has no 'Food Name' header (has the format changed?)")
    return version, groups


def fetch_all(client: httpx.Client, progress: Progress = lambda message, done=None, total=None: None,
              delay: float = 0.1) -> dict:
    """Assemble the whole database from the Food Agency's API, sequentially: 1 request for the food list,
    1 POST for the English Excel export (food groups and version; optional) and 1 request per food for its
    nutrient values -- about 2,600 requests, ~10 minutes, ~27 MB of JSON kept."""
    progress("Fetching the Swedish food list…")
    foods = _get_json(client, f"{API}/livsmedel", {"offset": 0, "limit": 10000, "sprak": 2})["livsmedel"]
    try:
        version, groups = _export_groups(client)
    except (httpx.HTTPError, ValueError, OSError, KeyError, zipfile.BadZipFile):  # food groups are optional detail
        version, groups = None, {}
    nutrients: dict[str, list[dict]] = {}
    total = len(foods)
    for done, food in enumerate(foods, 1):
        number = food["nummer"]
        values = _get_json(client, f"{API}/livsmedel/{number}/naringsvarden", {"sprak": 2})
        nutrients[str(number)] = [{k: v[k] for k in VALUE_FIELDS if k in v} for v in values]
        if done % 25 == 0 or done == total:
            progress(f"Fetched nutrients for {done:,} of {total:,} Swedish foods…", done, total)
        if delay:
            time.sleep(delay)
    return {"version": version, "foods": foods, "nutrients": nutrients, "groups": groups}


# --- Parsing -----------------------------------------------------------------------------


def _folic_acid_likely(name: str, group: str | None) -> bool:
    if group in FOLIC_ACID_GROUPS:
        return True
    if not FOLIC_ACID_NAME.search(name):
        return False
    return not (A_D_ONLY.search(name) and not PLANT_BASED.search(name)) or "folic" in name.lower()


def _is_rae(method: str | None) -> bool:
    """VITA's method: "... calculated from retinol and beta-carotene (Factor 1/12)", "... (factor 1/12 and 1/24)",
    or a recipe sum of such values; "(factor 1/6)" is retinol equivalents."""
    method = (method or "").lower()
    return "1/12" in method or method == RECIPE_METHOD


def _state(food: dict) -> tuple[str | None, str | None]:
    return COOKING.get((food.get("tillagningsmetod") or "").strip().lower(), (None, None))


def _food(food: dict, values: list[dict], group: str | None, version: str | None) -> ExternalFood:
    comp = Components(DERIVATION)
    name = " ".join(food["namn"].split())
    folic_acid = _folic_acid_likely(name, group)
    for value in values:
        code, unit, kind = value.get("euroFIRkod"), (value.get("enhet") or "").strip(), value.get("vardetypkod")
        if code == "ENERC":
            key = {"kcal": "energy_kcal", "kj": "energy_kj"}.get(unit.lower())
        else:
            key = MAPPING.get(code)
        if key is None or kind in UNKNOWN_TYPES or value.get("varde") is None:
            continue
        if (key == "folate_ug_dfe" and folic_acid) or (key in SPECIAL_UNITS and unit != SPECIAL_UNITS[key]):
            continue
        if key == "vitamin_a_ug":
            if not _is_rae(value.get("metodindikator")):
                continue  # not known to be RAE: derived from retinol + beta-carotene instead
            unit = "µg RAE"
        raw = 0 if kind in ZERO_TYPES else value["varde"]
        extra = FOLATE_CAVEAT if key == "folate_ug_dfe" else None
        marker = ZERO_TYPES.get(kind)
        if kind in LIMIT_TYPES and value["varde"]:
            marker = f"{marker} (<{value['varde']:g} {value.get('enhet') or ''})".replace(" )", ")")
        note = "; ".join(x for x in (extra, marker) if x)
        if len(DERIVATION) + 2 + len(note) > MAX_DERIVATION:
            note = note[: MAX_DERIVATION - len(DERIVATION) - 3] + "…"
        comp.add(key, raw, None if key in Components.SPECIAL else unit, note=note or None)

    number = str(food["nummer"])
    parsed = make_food(source=SOURCE, source_id=number, name=name,
                       data_type=f"{DATA_TYPE} {version}" if version else DATA_TYPE,
                       citation=f"{attribution(version).rstrip('.')}. Food {number}.", components=comp,
                       category=group, source_url=FOOD_URL.format(nr=number))
    if parsed.state is None:
        parsed.state, parsed.cooking_method = _state(food)
    return parsed


def parse(files: dict[str, Path]) -> Iterator[ExternalFood]:
    data = json.loads(files["data"].read_text(encoding="utf-8"))
    version, groups, nutrients = data.get("version"), data.get("groups") or {}, data.get("nutrients") or {}
    for food in data.get("foods") or []:
        if food.get("nummer") is None or not (food.get("namn") or "").strip():
            continue
        values = nutrients.get(str(food["nummer"]))
        if not values:
            continue
        parsed = _food(food, values, groups.get(str(food["nummer"])), version)
        if parsed.nutrients:
            yield parsed


if __name__ == "__main__":  # pragma: no cover - manual fetch: python -m app.sources.intl.se_livsmedel out.json
    import sys

    with httpx.Client(follow_redirects=True) as c:
        data = fetch_all(c, lambda m, d=None, t=None: print(m, flush=True))
    Path(sys.argv[1]).write_text(json.dumps(data), encoding="utf-8")
