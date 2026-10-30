"""German Nutrient Database (Bundeslebensmittelschlüssel, BLS 4.0, Max Rubner-Institut).

The download is a zip with one data workbook: a sheet with the BLS code, German name, English
name, then for each of 138 components three columns: the value ("CODE Name [unit/100g]"), its
data origin ("Datenherkunft") and a reference. Values are per 100 g edible portion. "-" =
missing, "TR" = trace, "<LOD"/"<LOQ" = below the detection/quantification limit. Most values
are calculated (from recipes, formulas or similar foods), so each value's data origin is kept
in its derivation.

Definition notes (BLS 4.0 documentation and components file):

- CHO is available carbohydrate (sugars + starch + oligosaccharides + polyols, as weight);
  total carbohydrate is CHO + total dietary fibre (FIBT).
- VITAA is RAE (retinol + beta-carotene/12 + other carotenoids/24) and is used directly;
  VITA is retinol equivalents and is not mapped.
- VITE is alpha-tocopherol. FOL is folate equivalents = food folate + 1.7 × synthetic folic
  acid, i.e. DFE. NIA is preformed niacin (niacin equivalents NIAEQ not mapped). VITK1 is
  phylloquinone (VITK, which adds menaquinones, is not mapped). Protein is N × 6.25.
- There is no trans fat or selenium. Monounsaturated fat (FAMS) is the sum of six cis
  isomers, as published.
"""

import io
import re
import zipfile
from collections.abc import Iterator
from pathlib import Path

import openpyxl

from app.services.datasets import BY_KEY
from app.sources.base import ExternalFood
from app.sources.intl.common import Components, make_food, unit_in

DATASET = BY_KEY["intl_bls"]
DATA_TYPE = "BLS 4.0"

# BLS component code -> (our nutrient code or Components special key, note on the value).
COMPONENTS = {
    "ENERCC": ("energy_kcal", None),
    "ENERCJ": ("energy_kj", None),
    "WATER": ("water_g", None),
    "PROT625": ("protein_g", "N × 6.25"),
    "FAT": ("fat_g", None),
    "CHO": ("available_carbs_g", None),
    "FIBT": ("fiber_g", None),
    "SUGAR": ("sugars_g", None),
    "ALC": ("alcohol_g", None),
    "FASAT": ("sat_fat_g", None),
    "FAMS": ("mono_fat_g", None),
    "FAPU": ("poly_fat_g", None),
    "CHORL": ("cholesterol_mg", None),
    "NA": ("sodium_mg", None),
    "K": ("potassium_mg", None),
    "CA": ("calcium_mg", None),
    "MG": ("magnesium_mg", None),
    "P": ("phosphorus_mg", None),
    "FE": ("iron_mg", None),
    "ZN": ("zinc_mg", None),
    "CU": ("copper_mg", None),
    "MN": ("manganese_mg", None),
    "ID": ("iodine_ug", None),
    "VITAA": ("vitamin_a_ug", "RAE as published"),
    "VITD": ("vitamin_d_ug", None),
    "VITE": ("vitamin_e_mg", None),
    "VITK1": ("vitamin_k_ug", None),
    "THIA": ("thiamin_mg", None),
    "RIBF": ("riboflavin_mg", None),
    "NIA": ("niacin_mg", None),
    "PANTAC": ("pantothenic_mg", None),
    "VITB6": ("vitamin_b6_mg", None),
    "BIOT": ("biotin_ug", None),
    "FOL": ("folate_ug_dfe", "folate equivalents (DFE)"),
    "VITB12": ("vitamin_b12_ug", None),
    "VITC": ("vitamin_c_mg", None),
}

# Data origin categories (BLS 4.0 documentation, section 4.2).
ORIGINS = {
    "Analyse": "analysis",
    "Rezeptberechnung": "recipe calculation",
    "Musterberechnung": "nutrient-pattern calculation",
    "Literatur": "literature",
    "Aggregation": "aggregated literature values",
    "Labelangabe": "product label",
    "Nährstoffdatenbank": "other nutrient database",
    "Übernommener Wert": "taken from a similar food",
    "Reskalierung": "rescaled (e.g. for water content)",
    "Logische Null": "logical zero",
    "Logische Annahme": "logical assumption",
    "Spuren": None,  # the value itself says "TR", which Components records as trace
    "Formelberechnung": "formula calculation",
}

# Main food groups: the first letter of the BLS code.
GROUPS = {
    "B": "Bread and rolls", "C": "Cereals and cereal products", "D": "Biscuits, cakes and pastries",
    "E": "Eggs and pasta", "F": "Fruit and fruit products", "G": "Vegetables and vegetable products",
    "H": "Pulses, nuts and seeds", "K": "Potatoes, starchy roots and mushrooms", "M": "Milk and dairy products",
    "N": "Non-alcoholic beverages", "P": "Alcoholic beverages", "Q": "Fats and oils",
    "R": "Seasonings, condiments and baking ingredients", "S": "Sugar, confectionery and ice cream",
    "T": "Fish and seafood", "U": "Meat", "V": "Game, poultry and offal", "W": "Sausages and meat products",
    "X": "Dishes: soups, sauces and side dishes", "Y": "Dishes: meals and desserts",
}

_HEADER = re.compile(r"^(\S+) .*\[")


def origin_note(raw) -> str | None:
    text = str(raw or "").strip()
    if not text or text == "-":
        return None
    english = ORIGINS.get(text, text)
    return f"origin: {english}" if english else None


def _workbook(path: Path):
    with zipfile.ZipFile(path) as zf:
        member = next((n for n in zf.namelist() if re.search(r"BLS_[\d_]+_Daten_.*\.xlsx$", n)), None)
        if member is None:
            raise ValueError("The BLS download contains no data workbook (BLS_*_Daten_*.xlsx)")
        data = zf.read(member)
    return openpyxl.load_workbook(io.BytesIO(data), read_only=True, data_only=True)


def parse(files: dict[str, Path]) -> Iterator[ExternalFood]:
    wb = _workbook(files["zip"])
    try:
        rows = wb.worksheets[0].iter_rows(values_only=True)
        header = [str(h or "").strip() for h in next(rows)]
        columns = []  # (value column, our key, unit, note)
        for i, label in enumerate(header):
            match = _HEADER.match(label)
            if match and match.group(1) in COMPONENTS:
                key, note = COMPONENTS[match.group(1)]
                columns.append((i, key, unit_in(label), note))
        for row in rows:
            code = str(row[0] or "").strip()
            name = str(row[2] or row[1] or "").strip()
            if not code or not name:
                continue
            comps = Components(DATA_TYPE)
            for i, key, unit, note in columns:
                origin = origin_note(row[i + 1]) if i + 1 < len(row) else None
                comps.add(key, row[i], unit, "; ".join(x for x in (note, origin) if x) or None)
            yield make_food(
                source=DATASET.source, source_id=code, name=name, data_type=DATA_TYPE, category=GROUPS.get(code[0]),
                citation=f"{DATASET.attribution.rstrip('.')}. Food {code}.", components=comps,
            )
    finally:
        wb.close()
