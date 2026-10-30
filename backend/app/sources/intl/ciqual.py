"""French food composition table Ciqual (ANSES), XML release.

Files (UTF-8 with BOM, values padded with spaces, decimal commas; "-" is missing,
"< x" below a limit, "traces" a trace):

- ``alim``: foods (alim_code, alim_nom_eng, alim_grp_code, ...)
- ``compo``: one row per food and constituent (teneur, code_confiance A-D); ~70 MB, streamed
- ``const``: constituents with names that carry the unit, e.g. "Sodium (mg/100g)"
- ``groups``: food group names in French and English

Definitions checked against the 2025 data:

- 328 energy (kcal) is calculated with the EU Regulation 1169/2011 factors; 327 is the same in kJ.
  The "N x Jones' factor" energies (332/333) are not used.
- 31000 "Carbohydrate" is available carbohydrate (INFOODS CHOAVL), so ours is 31000 + 34100 fibre.
- 51104 "Vitamin A activity, retinol equivalent" is tagged RAE and computed with beta-carotene/12, but
  it counts values below the quantification limit as half the limit; RAE is derived here from
  51200 retinol and 51330 beta-carotene instead (below-limit counts as 0), which covers the same foods.
- 53100 "Vitamin E" (INFOODS VITE-, method unspecified, never given together with 71010) is not mapped;
  71010 alpha-tocopherol is.
- 56702 is folate DFE (intrinsic folate + 1.7 x folic acid). Foods without it may have 56700 total
  folate, used as DFE (with that caveat) unless 56708 shows added folic acid or the name says the food is
  fortified with vitamins (folic acid is then usually not reported separately).
- 52100 vitamin D equals D2 + D3 (52200 + 52300) wherever all three are given.
"""

import re
import xml.etree.ElementTree as ET
from collections.abc import Iterator
from pathlib import Path

from app.services.datasets import BY_KEY
from app.sources.base import ExternalFood
from app.sources.intl.common import Components, make_food, parse_value, unit_in

DATASET = BY_KEY["intl_ciqual"]

# Ciqual const_code -> (our nutrient code or Components special key, extra note). Order matters where two
# codes feed one nutrient: the first value present wins.
MAPPING: dict[str, tuple[str, str | None]] = {
    "328": ("energy_kcal", "EU Regulation 1169/2011 factors"),
    "327": ("energy_kj", "EU Regulation 1169/2011 factors"),
    "25000": ("protein_g", None),  # N x Jones' factor
    "40000": ("fat_g", None),
    "31000": ("available_carbs_g", None),
    "34100": ("fiber_g", None),
    "32000": ("sugars_g", None),
    "40302": ("sat_fat_g", None),
    "40303": ("mono_fat_g", None),
    "40304": ("poly_fat_g", None),
    "75100": ("cholesterol_mg", None),
    "400": ("water_g", None),
    "60000": ("alcohol_g", None),
    "10110": ("sodium_mg", None),
    "10190": ("potassium_mg", None),
    "10200": ("calcium_mg", None),
    "10260": ("iron_mg", None),
    "10120": ("magnesium_mg", None),
    "10150": ("phosphorus_mg", None),
    "10300": ("zinc_mg", None),
    "10290": ("copper_mg", None),
    "10251": ("manganese_mg", None),
    "10340": ("selenium_ug", None),
    "10530": ("iodine_ug", None),
    "51200": ("retinol_ug", None),
    "51330": ("beta_carotene_ug", None),
    "52100": ("vitamin_d_ug", None),
    "71010": ("vitamin_e_mg", None),
    "54101": ("vitamin_k_ug", None),
    "55100": ("vitamin_c_mg", None),
    "56100": ("thiamin_mg", None),
    "56200": ("riboflavin_mg", None),
    "56310": ("niacin_mg", None),
    "56400": ("pantothenic_mg", None),
    "56500": ("vitamin_b6_mg", None),
    "56600": ("vitamin_b12_ug", None),
    "56702": ("folate_ug_dfe", None),
}
TOTAL_FOLATE, FOLIC_ACID = "56700", "56708"
FOLATE_CAVEAT = "total folate as DFE (no folic acid assumed)"
VITAMIN_FORTIFIED = re.compile(r"multivitamin|(?<!not )fortifi?ed with vitamin(?!\s*D\b)", re.IGNORECASE)
# Units the special keys must be published in (they are not converted).
SPECIAL_UNITS = {"energy_kj": "kj", "available_carbs_g": "g", "retinol_ug": "µg", "beta_carotene_ug": "µg"}
# Values we derive from components, and the components whose confidence codes they carry.
DERIVED = {"carbs_g": ("available_carbs_g", "fiber_g"), "vitamin_a_ug": ("retinol_ug", "beta_carotene_ug"),
           "energy_kcal": ("energy_kj",)}


def _records(path: Path, tag: str) -> Iterator[dict[str, str]]:
    """Stream ``<tag>`` records as {child tag: stripped text}, freeing parsed rows as it goes."""
    context = ET.iterparse(path, events=("start", "end"))
    _, root = next(context)
    for event, el in context:
        if event == "end" and el.tag == tag:
            yield {child.tag: (child.text or "").strip() for child in el}
            root.clear()


def _units(path: Path) -> dict[str, str]:
    units = {}
    for row in _records(path, "CONST"):
        unit = unit_in(row.get("const_nom_eng", "")) or unit_in(row.get("const_nom_fr", ""))
        if unit:
            units[row["const_code"]] = unit
    return units


def _groups(path: Path) -> dict[str, str]:
    names = {}
    for row in _records(path, "ALIM_GRP"):
        name = row.get("alim_grp_nom_eng") or row.get("alim_grp_nom_fr") or ""
        if name and name != "-":
            names[row["alim_grp_code"]] = name[:1].upper() + name[1:]
    return names


def _composition(path: Path) -> dict[str, dict[str, tuple[str, str]]]:
    """alim_code -> const_code -> (published value, confidence code), for the constituents we use."""
    wanted = set(MAPPING) | {TOTAL_FOLATE, FOLIC_ACID}
    out: dict[str, dict[str, tuple[str, str]]] = {}
    for row in _records(path, "COMPO"):
        if row.get("const_code") in wanted:
            out.setdefault(row["alim_code"], {})[row["const_code"]] = (row.get("teneur", ""), row.get("code_confiance", ""))
    return out


def _food(alim: dict[str, str], values: dict[str, tuple[str, str]], units: dict[str, str],
          groups: dict[str, str]) -> ExternalFood:
    comp = Components("Ciqual")
    confidence: dict[str, str] = {}

    def add(key: str, const: str, extra: str | None) -> None:
        raw, conf = values.get(const, (None, ""))
        unit = units.get(const)
        if raw is None or unit is None:
            return
        if key in SPECIAL_UNITS and unit.lower() != SPECIAL_UNITS[key]:
            return
        note = "; ".join(x for x in (f"confidence {conf}" if conf else None, extra) if x)
        comp.add(key, raw, unit, note=note or None)
        if key in comp.values and conf:
            confidence.setdefault(key, conf)

    for const, (key, extra) in MAPPING.items():
        add(key, const, extra)
    name = alim.get("alim_nom_eng") or alim["alim_nom_fr"]
    folic_acid, _ = parse_value(values.get(FOLIC_ACID, (None, ""))[0])
    if not folic_acid and not VITAMIN_FORTIFIED.search(name):  # total folate equals DFE only without folic acid
        add("folate_ug_dfe", TOTAL_FOLATE, FOLATE_CAVEAT)

    code = alim["alim_code"]
    food = make_food(source=DATASET.source, source_id=code, name=name,
                     data_type=f"Ciqual {DATASET.release}", citation=f"{DATASET.attribution.rstrip('.')}. Food {code}.",
                     components=comp, category=groups.get(alim.get("alim_grp_code", "")))
    for target, parts in DERIVED.items():
        if target in food.nutrients and target not in comp.values and all(p in confidence for p in parts):
            amount, reason = food.nutrients[target]
            food.nutrients[target] = (amount, f"{reason} (confidence {' + '.join(confidence[p] for p in parts)})")
    return food


def parse(files: dict[str, Path]) -> Iterator[ExternalFood]:
    units = _units(files["const"])
    groups = _groups(files["groups"])
    composition = _composition(files["compo"])
    for alim in _records(files["alim"], "ALIM"):
        values = composition.get(alim.get("alim_code", ""))
        if not values:
            continue
        food = _food(alim, values, units, groups)
        if food.nutrients:
            yield food
