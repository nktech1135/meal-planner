"""Swiss Food Composition Database (Federal Food Safety and Veterinary Office FSVO), V 7.1 (01.07.2026).

File ``data`` (Swiss_food_composition_database.xlsx), with sheets:

- ``Generic Foods`` (1,216 foods) and ``Branded foods`` (30: mineral waters and four spirits): a title row,
  a blank row, then the header (ID, ID V 4.0, ID SwissFIR, Name, Synonyms, Category, Density, Matrix unit),
  then per nutrient three columns: the value ("Protein (g)"), "Derivation of value" and "Source" (one or
  more ``;``-separated ids). Values are per 100 g edible portion. "n.d." = no data (missing), "tr." = trace,
  "<x" = below the limit x.
- ``Sources``: source id -> reference.

The branded foods are manufacturer data (mineralisation tables of the Swiss mineral water association,
spirits makers' certificates) and are kept with trust level "label".

Definitions (naehrwertdaten.ch "Nutrients" page, checked against the data):

- Energy is calculated with the Swiss FoodO factors (as EU 1169/2011: available carbohydrate and protein 4
  kcal/g, fat 9, alcohol 7, fibre 2); kcal is used as published.
- "Carbohydrates, available" is available carbohydrate, so ours adds dietary fibre.
- Protein is N x 6.25.
- "Vitamin A activity, RAE" (retinol + beta-carotene equivalents/12) is used as published; the RE column
  (carotenoids /6) is not mapped.
- Vitamin E is alpha-tocopherol (since V 6.5; FSVO notes a few values may still include other
  tocopherols).
- Folate is total folate, used as DFE with that caveat, except for foods named fortified / with vitamins and
  supplements, where it includes folic acid.
- Vitamin D is D2 + D3, but "for a small number of foods (e.g. eggs)" also counts 25-hydroxy D3 one to one;
  it is mapped except for the Eggs category.
- Niacin is preformed niacin; niacin equivalents are not mapped. Salt is sodium x 2.5 and is not mapped.
"""

import re
from collections.abc import Iterator
from pathlib import Path

import openpyxl

from app.sources.base import ExternalFood
from app.sources.intl.common import Components, make_food, parse_value, unit_in

SOURCE = "swiss"
DATA_TYPE = "Swiss FCDB 7.1"
ATTRIBUTION = ("Swiss Food Composition Database V 7.1 (01.07.2026), Federal Food Safety and Veterinary Office FSVO, "
               "www.naehrwertdaten.ch")
MAX_DERIVATION = 120  # FoodNutrient.derivation column length
SHEETS = {"Generic Foods": "analytical", "Branded foods": "label"}

# Nutrient column header -> (our nutrient code or Components special key, note on the value).
COLUMNS: dict[str, tuple[str, str | None]] = {
    "Energy, kilocalories (kcal)": ("energy_kcal", None),
    "Energy, kilojoules (kJ)": ("energy_kj", None),
    "Fat, total (g)": ("fat_g", None),
    "Fatty acids, saturated (g)": ("sat_fat_g", None),
    "Fatty acids, monounsaturated (g)": ("mono_fat_g", None),
    "Fatty acids, polyunsaturated (g)": ("poly_fat_g", None),
    "Cholesterol (mg)": ("cholesterol_mg", None),
    "Carbohydrates, available (g)": ("available_carbs_g", None),
    "Sugars (g)": ("sugars_g", None),
    "Dietary fibres (g)": ("fiber_g", None),
    "Protein (g)": ("protein_g", "N × 6.25"),
    "Alcohol (g)": ("alcohol_g", None),
    "Water (g)": ("water_g", None),
    "Vitamin A activity, RAE (µg)": ("vitamin_a_ug", "RAE as published"),
    "Vitamin B1 (thiamine) (mg)": ("thiamin_mg", None),
    "Vitamin B2 (riboflavin) (mg)": ("riboflavin_mg", None),
    "Vitamin B6 (pyridoxine) (mg)": ("vitamin_b6_mg", None),
    "Vitamin B12 (cobalamin) (µg)": ("vitamin_b12_ug", None),
    "Niacin (mg)": ("niacin_mg", "preformed niacin"),
    "Pantothenic acid (mg)": ("pantothenic_mg", None),
    "Vitamin C (ascorbic acid) (mg)": ("vitamin_c_mg", None),
    "Vitamin E (α-tocopherol) (mg)": ("vitamin_e_mg", None),
    "Potassium (K) (mg)": ("potassium_mg", None),
    "Sodium (Na) (mg)": ("sodium_mg", None),
    "Calcium (Ca) (mg)": ("calcium_mg", None),
    "Magnesium (Mg) (mg)": ("magnesium_mg", None),
    "Phosphorus (P) (mg)": ("phosphorus_mg", None),
    "Iron (Fe) (mg)": ("iron_mg", None),
    "Iodide (I) (µg)": ("iodine_ug", None),
    "Zinc (Zn) (mg)": ("zinc_mg", None),
    "Selenium (Se) (µg)": ("selenium_ug", None),
}
FOLATE, VITAMIN_D = "Folate (µg)", "Vitamin D (calciferol) (µg)"
FOLATE_NOTE = "total folate as DFE (no folic acid assumed)"
FOLIC_ACID = re.compile(r"fortified|vitamin|supplement", re.IGNORECASE)  # name or category
UNITS = {"energy_kj": "kj", "available_carbs_g": "g"}  # special keys are not converted
ORIGINS = {
    "Calculation on the basis of ingredients": "recipe calculation",
    "Automated calculation": "calculated",
    "Estimation": "estimated",
    "-": None,
}


def _clean(text) -> str:
    return re.sub(r"\s+", " ", str(text or "")).strip()


def category(raw) -> str | None:
    """'Fruit/Fresh fruit;Non-alcoholic beverages/...' -> 'Fruit: Fresh fruit' (the first category)."""
    first = _clean(raw).split(";")[0].strip()
    if not first:
        return None
    main, _, sub = first.partition("/")
    return f"{main}: {sub}" if sub else main


def _source_note(source, sources: dict[str, str], budget: int) -> str | None:
    ids = [s.strip() for s in re.split(r"[;,]", str(source or "")) if s.strip()]
    if not ids:
        return None
    note = f"sources {', '.join(ids)}" if len(ids) > 1 else f"source {ids[0]}"
    if len(ids) == 1 and sources.get(ids[0]):
        note = f"{note}: {sources[ids[0]]}"
    return note if len(note) <= budget else note[: max(budget - 1, 0)].rstrip() + "…"


def _origin(raw) -> str | None:
    text = _clean(raw)
    return ORIGINS.get(text, text) if text else None


def _food(row: tuple, columns: dict[str, int], sources: dict[str, str], trust: str) -> ExternalFood | None:
    food_id, name = row[columns["ID"]], _clean(row[columns["Name"]])
    matrix = _clean(row[columns["Matrix unit"]]).lower() if "Matrix unit" in columns else ""
    if food_id is None or not name or (matrix and "100g" not in matrix.replace(" ", "")):
        return None
    group = _clean(row[columns["Category"]])
    comp = Components(DATA_TYPE)

    def add(header: str, key: str, extra: str | None) -> None:
        i = columns.get(header)
        if i is None:
            return
        raw = row[i]
        _, flag = parse_value(raw)
        unit = unit_in(header)
        if key in UNITS:
            if (unit or "").lower() != UNITS[key]:
                return
            unit = None
        fixed = [x for x in (extra, _origin(row[i + 1])) if x]
        budget = MAX_DERIVATION - len(DATA_TYPE) - sum(len(x) + 2 for x in (*fixed, flag) if x) - 2
        note = "; ".join(x for x in (*fixed, _source_note(row[i + 2], sources, budget)) if x)
        comp.add(key, raw, unit, note=note or None)

    for header, (key, extra) in COLUMNS.items():
        add(header, key, extra)
    if not group.startswith("Eggs"):  # egg vitamin D includes 25-hydroxy D3
        add(VITAMIN_D, "vitamin_d_ug", None)
    if not FOLIC_ACID.search(f"{name} {group}"):
        add(FOLATE, "folate_ug_dfe", FOLATE_NOTE)

    density = parse_value(row[columns["Density"]])[0] if "Density" in columns else None
    food = make_food(source=SOURCE, source_id=str(food_id), name=name,
                     data_type=DATA_TYPE if trust == "analytical" else f"{DATA_TYPE} (branded)",
                     citation=f"{ATTRIBUTION.rstrip('.')}. Food {food_id}.", components=comp, category=category(group),
                     portions=[("100 mL", round(100 * density, 1))] if density else [], trust_level=trust)
    return food


def _header(rows) -> list[str]:
    for row in rows:
        if row and _clean(row[0]) == "ID":
            return [_clean(h) for h in row]
    raise ValueError("No header row (starting with 'ID') in the Swiss food composition workbook")


def parse(files: dict[str, Path]) -> Iterator[ExternalFood]:
    wb = openpyxl.load_workbook(files["data"], read_only=True, data_only=True)
    try:
        sources: dict[str, str] = {}
        if "Sources" in wb.sheetnames:
            rows = wb["Sources"].iter_rows(values_only=True)
            _header(rows)
            sources = {_clean(r[0]): _clean(r[1]) for r in rows if r and r[0] is not None and len(r) > 1}
        for sheet, trust in SHEETS.items():
            if sheet not in wb.sheetnames:
                continue
            rows = wb[sheet].iter_rows(values_only=True)
            header = _header(rows)
            columns: dict[str, int] = {}
            for i, label in enumerate(header):
                columns.setdefault(label, i)  # nutrient value columns; the derivation/source follow each
            missing = [h for h in ("Name", "Category", *COLUMNS) if h not in columns]
            if missing:
                raise ValueError(f"Swiss food composition workbook: missing columns {missing}")
            for row in rows:
                if not row or row[0] is None:
                    continue
                food = _food(row, columns, sources, trust)
                if food is not None and food.nutrients:
                    yield food
    finally:
        wb.close()
