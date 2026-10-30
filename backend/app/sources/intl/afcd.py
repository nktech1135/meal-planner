"""Australian Food Composition Database (AFCD) Release 3, Food Standards Australia New Zealand.

Files: ``profiles`` (Nutrient profiles workbook; we read the "All solids & liquids per 100 g"
sheet, header on row 3) and ``details`` (Food details workbook; its specific gravity gives
liquids a 100 mL portion). Mappings were checked against the Release 3 Nutrient details
workbook (INFOODS tagnames and equations):

- Energy is published only in kJ; "Energy with dietary fibre, equated" (ENERC) is converted.
- Carbohydrate: "Available carbohydrate, with sugar alcohols" + total dietary fibre (FIBTG),
  which matches total carbohydrate by difference better than the variant without polyols.
- Vitamin A (RAE) = retinol + beta-carotene equivalents/12. AFCD's beta-carotene equivalents
  are beta-carotene + (alpha-carotene + cryptoxanthin)/2, so this is exactly the IOM RAE.
  "Vitamin A retinol equivalents" (RE, carotenoids /6) is not mapped.
- Vitamin D = cholecalciferol (D3) + ergocalciferol (D2), as in USDA; "Vitamin D3
  equivalents" also counts 25-hydroxy forms x5 and is not mapped.
- Vitamin E = alpha-tocopherol; AFCD's "Vitamin E" (alpha + beta/2 + gamma/10) is not mapped.
- Folate: "Dietary folate equivalents" (natural folate + 1.67 x folic acid) maps directly.
- Niacin is preformed niacin (not niacin equivalents).
- Added sugars are not mapped: AFCD (AUSNUT) added sugars exclude honey and fruit-juice
  concentrates, which the U.S. definition includes.

AFCD records values below the limit of reporting, and zeros it imputes, as plain 0; the file
does not distinguish them from measured zeros, so they are stored as 0 without a note.
"""

import re
from collections.abc import Iterator
from pathlib import Path

import openpyxl

from app.services.datasets import BY_KEY
from app.sources.base import ExternalFood
from app.sources.intl.common import Components, make_food, parse_value, unit_in

DATASET = BY_KEY["intl_afcd"]
SHEET = "All solids & liquids per 100 g"
DATA_TYPE = "AFCD Release 3"

# Normalized column header -> our nutrient code (or a Components special key).
COLUMNS = {
    "Energy with dietary fibre, equated (kJ)": "energy_kj",
    "Moisture (water) (g)": "water_g",
    "Protein (g)": "protein_g",
    "Fat, total (g)": "fat_g",
    "Total dietary fibre (g)": "fiber_g",
    "Alcohol (g)": "alcohol_g",
    "Total sugars (g)": "sugars_g",
    "Available carbohydrate, with sugar alcohols (g)": "available_carbs_g",
    "Total saturated fatty acids, equated (g)": "sat_fat_g",
    "Total monounsaturated fatty acids, equated (g)": "mono_fat_g",
    "Total polyunsaturated fatty acids, equated (g)": "poly_fat_g",
    "Total trans fatty acids, imputed (mg)": "trans_fat_g",
    "Cholesterol (mg)": "cholesterol_mg",
    "Caffeine (mg)": "caffeine_mg",
    "Sodium (Na) (mg)": "sodium_mg",
    "Potassium (K) (mg)": "potassium_mg",
    "Calcium (Ca) (mg)": "calcium_mg",
    "Iron (Fe) (mg)": "iron_mg",
    "Magnesium (Mg) (mg)": "magnesium_mg",
    "Phosphorus (P) (mg)": "phosphorus_mg",
    "Zinc (Zn) (mg)": "zinc_mg",
    "Copper (Cu) (mg)": "copper_mg",
    "Manganese (Mn) (mg)": "manganese_mg",
    "Selenium (Se) (ug)": "selenium_ug",
    "Iodine (I) (ug)": "iodine_ug",
    "Vitamin C (mg)": "vitamin_c_mg",
    "Alpha tocopherol (mg)": "vitamin_e_mg",
    "Thiamin (B1) (mg)": "thiamin_mg",
    "Riboflavin (B2) (mg)": "riboflavin_mg",
    "Niacin (B3) (mg)": "niacin_mg",
    "Pantothenic acid (B5) (mg)": "pantothenic_mg",
    "Pyridoxine (B6) (mg)": "vitamin_b6_mg",
    "Biotin (B7) (ug)": "biotin_ug",
    "Dietary folate equivalents (ug)": "folate_ug_dfe",
    "Cobalamin (B12) (ug)": "vitamin_b12_ug",
}
# Columns combined into one of our nutrients below.
RETINOL = "Retinol (preformed vitamin A) (ug)"
CAROTENE_EQ = "Beta-carotene equivalents (provitamin A) (ug)"
VITAMIN_D3 = "Cholecalciferol (D3) (ug)"
VITAMIN_D2 = "Ergocalciferol (D2) (ug)"
NOTES = {"trans_fat_g": "imputed where not analysed"}

# AUSNUT 2023 major food groups: the first two digits of an AFCD classification code.
GROUPS = {
    "11": "Non-alcoholic beverages", "12": "Cereals and cereal products", "13": "Cereal based products and dishes",
    "14": "Fats and oils", "15": "Fish and seafood products and dishes", "16": "Fruit products and dishes",
    "17": "Egg products and dishes", "18": "Meat, poultry and game products and dishes", "19": "Milk products and dishes",
    "20": "Dairy and meat substitutes", "21": "Soup", "22": "Seed and nut products and dishes",
    "23": "Savoury sauces and condiments", "24": "Vegetable products and dishes",
    "25": "Legume and pulse products and dishes", "26": "Snack foods", "27": "Sugar products and dishes",
    "28": "Confectionery and cereal, nut, fruit and seed bars", "29": "Alcoholic beverages",
    "30": "Special dietary foods", "31": "Miscellaneous", "32": "Infant formulae and foods",
    "33": "Reptiles, amphibia and insects", "34": "Dietary supplements",
}


def _header(text) -> str:
    """'Iron (Fe) \\n(mg)' -> 'Iron (Fe) (mg)'; 'Sucrose\\n(g)' -> 'Sucrose (g)'."""
    return re.sub(r"\s*\(\s*", " (", re.sub(r"\s+", " ", str(text or ""))).strip()


def _rows(path: Path, sheet: str, header_row: int = 3) -> Iterator[dict[str, object]]:
    wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
    try:
        rows = wb[sheet].iter_rows(min_row=header_row, values_only=True)
        header = [_header(h) for h in next(rows)]
        for row in rows:
            if row and row[0]:
                yield dict(zip(header, row, strict=False))
    finally:
        wb.close()


def _specific_gravity(path: Path | None) -> dict[str, float]:
    if path is None:
        return {}
    out = {}
    for row in _rows(path, "Food details"):
        sg, _ = parse_value(row.get("Specific Gravity"))
        if sg:  # solids are given a default of 0
            out[str(row["Public Food Key"]).strip()] = sg
    return out


def _both(row: dict, a: str, b: str) -> tuple[float, float] | None:
    x, y = parse_value(row.get(a))[0], parse_value(row.get(b))[0]
    return None if x is None or y is None else (x, y)


def parse(files: dict[str, Path]) -> Iterator[ExternalFood]:
    gravity = _specific_gravity(files.get("details"))
    seen_columns = False
    for row in _rows(files["profiles"], SHEET):
        if not seen_columns:
            missing = [h for h in COLUMNS if h not in row]
            if missing:
                raise ValueError(f"AFCD nutrient profiles: columns not found (has the format changed?): {missing}")
            seen_columns = True
        key = str(row["Public Food Key"]).strip()
        derivation = str(row.get("Derivation") or "").strip()
        comp = Components(f"AFCD: {derivation}" if derivation else "AFCD")
        for header, code in COLUMNS.items():
            comp.add(code, row[header], unit_in(header), NOTES.get(code))
        vitamin_a = _both(row, RETINOL, CAROTENE_EQ)
        if vitamin_a:
            comp.add("vitamin_a_ug", vitamin_a[0] + vitamin_a[1] / 12, "µg rae",
                     "RAE = retinol + beta-carotene equivalents/12")
        vitamin_d = _both(row, VITAMIN_D3, VITAMIN_D2)
        if vitamin_d:
            comp.add("vitamin_d_ug", sum(vitamin_d), "µg", "D3 + D2")
        classification = str(row.get("Classification") or "").strip()
        sg = gravity.get(key)
        yield make_food(
            source=DATASET.source, source_id=key, name=str(row["Food Name"]), data_type=DATA_TYPE,
            category=GROUPS.get(classification[:2]), citation=f"{DATASET.attribution.rstrip('.')}. Food {key}.",
            components=comp, portions=[("100 mL", round(100 * sg, 1))] if sg else [],
        )
