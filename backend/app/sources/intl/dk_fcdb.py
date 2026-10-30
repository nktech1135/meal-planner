"""Danish Food Composition Database (FCDB, formerly Frida), DTU National Food Institute, version 6.1 (May 2026).

File ``data`` (FCDB_6.1_Dataset.xlsx); the sheets used are:

- ``Data_Normalised``: one row per food and parameter (FoodID, FødevareNavn, FoodName, ParameterID, ...,
  ResVal, Min, Max, Median, NumberOfDeterminations, Source, SourceFood). Values are per 100 g edible portion.
  Every published value is a number; the text "NULL" marks an empty cell. There are no trace or
  below-limit markers (such values are published as 0); a parameter that isn't listed is unknown.
  Source is one or more comma-separated ids from the ``Source`` sheet; each value records them.
- ``Parameter``: ParameterID -> name, unit ("g/100g", "RE (µg/100g)", "alfa-TE", "NE", ...) and EuroFIR code.
- ``Food`` / ``FoodGroup``: each food's group, with English names, two levels deep.
- ``Source``: reference titles (English).

Definitions checked against the 6.1 data:

- Energy (kcal, 356) is calculated with 4 kcal/g protein and available carbohydrate, 9 fat, 2 fibre, 7
  alcohol and is used as published; the "labelling" variants (316/359, 317, 318) are not used.
- "Carbohydrate by difference" (170) equals available carbohydrate (172) + dietary fibre (168) in all but
  four foods (where available carbohydrate is clamped to 0), i.e. total carbohydrate; it is mapped directly.
- Vitamin A (12) is RE: retinol + beta-carotene/6, exactly, and is not mapped. RAE = retinol (225) +
  all-trans beta-carotene (303)/12. Alpha-carotene and cryptoxanthin are not published (nor in the RE).
- Vitamin E (135) is alpha-tocopherol equivalents (unit "alfa-TE") and is not mapped; alpha-tocopherol
  (276) is.
- Vitamin D (126) is D3 + D2 + 2.5 x 25-hydroxy vitamin D (meat, milk, eggs). Where 25-hydroxy D is
  above 0, ours is D3 + D2 (128 + 127) instead.
- Folate (143) is total folate, used as DFE with that caveat, except for foods likely to contain folic
  acid: infant formulas, foods named fortified/enriched/with added vitamins, ready-to-eat breakfast
  cereals (several are clearly fortified, e.g. Rice Krispies at 292 µg) and energy drinks.
- Niacin (294) is preformed niacin; niacin equivalents (203, unit "NE") are not mapped. Thiamin is 37
  (36 duplicates it for six foods).
- Total sugars are "Sum sugars" (245). Added (417) and free sugars (418) are estimates by a Swedish
  procedure that gives honey no added sugar, unlike the U.S. definition, so they are not mapped.
- Salt (327) is not mapped: sodium (201) is given for every food.
"""

import re
from collections.abc import Iterator
from pathlib import Path

import openpyxl

from app.sources.base import ExternalFood
from app.sources.intl.common import Components, make_food, parse_value

SOURCE = "dk_fcdb"
DATA_TYPE = "Danish FCDB 6.1"
ATTRIBUTION = ("The Danish Food Composition Database (http://fcdb.fooddata.dk), version 6.1, May 2026, The Food "
               "Institute, Technical University of Denmark. Licensed under CC BY 4.0.")
MAX_DERIVATION = 120  # FoodNutrient.derivation column length

# ParameterID -> (our nutrient code or Components special key, note on the value). Order matters where two
# parameters feed one nutrient: the first value present wins.
PARAMETERS: dict[int, tuple[str, str | None]] = {
    356: ("energy_kcal", None),
    137: ("energy_kj", None),
    218: ("protein_g", None),
    141: ("fat_g", None),
    170: ("carbs_g", "by difference"),
    172: ("available_carbs_g", None),
    168: ("fiber_g", None),
    245: ("sugars_g", None),
    248: ("sat_fat_g", None),
    247: ("mono_fat_g", None),
    251: ("poly_fat_g", None),
    261: ("trans_fat_g", None),
    115: ("cholesterol_mg", None),
    268: ("water_g", None),
    19: ("alcohol_g", None),
    121: ("caffeine_mg", None),
    201: ("sodium_mg", None),
    165: ("potassium_mg", None),
    108: ("calcium_mg", None),
    162: ("iron_mg", None),
    184: ("magnesium_mg", None),
    214: ("phosphorus_mg", None),
    274: ("zinc_mg", None),
    166: ("copper_mg", None),
    187: ("manganese_mg", None),
    230: ("selenium_ug", None),
    163: ("iodine_ug", None),
    225: ("retinol_ug", None),
    303: ("beta_carotene_ug", None),
    276: ("vitamin_e_mg", None),
    164: ("vitamin_k_ug", None),
    37: ("thiamin_mg", None),
    36: ("thiamin_mg", None),
    39: ("riboflavin_mg", None),
    294: ("niacin_mg", "preformed niacin"),
    210: ("pantothenic_mg", None),
    40: ("vitamin_b6_mg", None),
    42: ("biotin_ug", None),
    38: ("vitamin_b12_ug", None),
    47: ("vitamin_c_mg", None),
    116: ("choline_mg", None),
}
VITAMIN_D, VITAMIN_D3, VITAMIN_D2, HYDROXY_D3, HYDROXY_D2 = 126, 128, 127, 11, 354
FOLATE, DENSITY = 143, 363
FOLATE_NOTE = "total folate as DFE (no folic acid assumed)"
D_NOTE = "D3 + D2 (excludes 25-OH D)"
FOLIC_ACID = re.compile(r"formula|\bfortified|(?<!not )enriched|added [\w ]*vitamin|breakfast cereal|corn ?flakes|"
                        r"rice krispies|supplement|energy drink", re.IGNORECASE)
_UNIT = re.compile(r"^(kJ|kcal|g|mg|µg)\s*/\s*100\s*g$")


def _rows(wb, sheet: str) -> Iterator[dict]:
    rows = wb[sheet].iter_rows(values_only=True)
    header = [str(h).strip() if h is not None else "" for h in next(rows)]
    for row in rows:
        yield {h: (None if v == "NULL" else v) for h, v in zip(header, row, strict=False) if h}


def _text(value) -> str:
    return str(value).strip() if value is not None else ""


def _units(wb) -> dict[int, str]:
    """ParameterID -> plain mass/energy unit; parameters in RE, alpha-TE, NE, % etc. are left out."""
    units = {}
    for row in _rows(wb, "Parameter"):
        match = _UNIT.match(_text(row.get("Unit")).replace("μ", "µ"))
        if match and row.get("ParameterID") is not None:
            units[int(row["ParameterID"])] = match.group(1)
    return units


def _groups(wb) -> dict[int, str]:
    """FoodGroupID -> 'Main group: Sub group' (English), below the top-level 'Retail trade' etc."""
    rows = {int(r["FoodGroupID"]): r for r in _rows(wb, "FoodGroup") if r.get("FoodGroupID") is not None}
    out = {}
    for gid, row in rows.items():
        name = _text(row.get("GroupNameUK"))
        parent = rows.get(int(row.get("ParantFoodGroupID") or 0))
        if parent is not None and parent is not row and int(parent.get("Hieraky") or 0) > 1:
            out[gid] = f"{_text(parent.get('GroupNameUK'))}: {name}"
        else:
            out[gid] = name
    return out


def _source_note(source, titles: dict[str, str], budget: int) -> str | None:
    ids = [s.strip() for s in _text(source).split(",") if s.strip()]
    if not ids:
        return None
    if len(ids) > 1:
        note = f"sources {', '.join(ids)}"
    else:
        note = f"source {ids[0]}"
        if titles.get(ids[0]):
            note = f"{note}: {titles[ids[0]]}"
    return note if len(note) <= budget else note[: max(budget - 1, 0)].rstrip() + "…"


def _food(food_id: int, name: str, values: dict[int, tuple], units: dict[int, str], titles: dict[str, str],
          category: str | None) -> ExternalFood:
    comp = Components(DATA_TYPE)

    def add(key: str, raw, unit: str | None, extra: str | None, source) -> None:
        _, flag = parse_value(raw)
        fixed = [x for x in (extra, flag) if x]
        budget = MAX_DERIVATION - len(DATA_TYPE) - sum(len(x) + 2 for x in fixed) - 2
        note = "; ".join(x for x in (extra, _source_note(source, titles, budget)) if x)
        comp.add(key, raw, unit, note=note or None)

    def value(parameter: int) -> float | None:
        return parse_value(values.get(parameter, (None, None))[0])[0]

    for parameter, (key, extra) in PARAMETERS.items():
        if parameter in values and parameter in units:
            add(key, values[parameter][0], units[parameter], extra, values[parameter][1])

    hydroxy = sum(v for v in (value(HYDROXY_D3), value(HYDROXY_D2)) if v)
    if hydroxy > 0:  # Vitamin D counts 25-hydroxy D x 2.5; ours is D2 + D3 only
        d3, d2 = value(VITAMIN_D3), value(VITAMIN_D2)
        if d3 is not None:
            add("vitamin_d_ug", d3 + (d2 or 0), "µg", D_NOTE, values[VITAMIN_D3][1])
    elif VITAMIN_D in values:
        add("vitamin_d_ug", values[VITAMIN_D][0], units.get(VITAMIN_D, "µg"), None, values[VITAMIN_D][1])

    if FOLATE in values and not FOLIC_ACID.search(name):
        add("folate_ug_dfe", values[FOLATE][0], units.get(FOLATE, "µg"), FOLATE_NOTE, values[FOLATE][1])

    density = value(DENSITY)
    return make_food(source=SOURCE, source_id=str(food_id), name=name, data_type=DATA_TYPE, category=category,
                     citation=f"{ATTRIBUTION.rstrip('.')}. Food {food_id}.", components=comp,
                     portions=[("100 mL", round(100 * density, 1))] if density else [])


def parse(files: dict[str, Path]) -> Iterator[ExternalFood]:
    wb = openpyxl.load_workbook(files["data"], read_only=True, data_only=True)
    try:
        units = _units(wb)
        groups = _groups(wb)
        titles = {_text(r.get("SourceID")): _text(r.get("TitleEnglish") or r.get("TitleOriginal"))
                  for r in _rows(wb, "Source") if r.get("SourceID") is not None}
        food_group = {int(r["FoodID"]): r.get("FoodGroupID") for r in _rows(wb, "Food") if r.get("FoodID") is not None}
        names: dict[int, str] = {}
        values: dict[int, dict[int, tuple]] = {}
        for row in _rows(wb, "Data_Normalised"):
            food_id, parameter = row.get("FoodID"), row.get("ParameterID")
            if food_id is None or parameter is None:
                continue
            food_id = int(food_id)
            names.setdefault(food_id, _text(row.get("FoodName")) or _text(row.get("FødevareNavn")))
            values.setdefault(food_id, {})[int(parameter)] = (row.get("ResVal"), row.get("Source"))
    finally:
        wb.close()
    for food_id, name in names.items():
        if not name:
            continue
        group = food_group.get(food_id)
        food = _food(food_id, name, values[food_id], units, titles, groups.get(int(group)) if group is not None else None)
        if food.nutrients:
            yield food
