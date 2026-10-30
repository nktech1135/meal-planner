"""Canonical nutrient catalog and data-trust levels.

Nutrient codes are our own stable identifiers. ``fdc_numbers`` are the USDA
nutrient numbers (the legacy SR numbers FDC still exposes as ``nutrient.number``);
Nutritionix ``attr_id`` uses the same numbering. When several FDC numbers map to
one code they are listed in preference order (e.g. Foundation foods report
energy as Atwater factors 958/957 instead of 208).
"""

from dataclasses import dataclass
from enum import StrEnum


class Trust(StrEnum):
    """How much a nutrient value can be relied on, best first."""

    ANALYTICAL = "analytical"  # government lab-analysed / compiled data (USDA Foundation, SR Legacy, FNDDS)
    LABEL = "label"  # manufacturer label declarations catalogued by a government database (FDC Branded, NIH DSLD)
    COMMERCIAL = "commercial"  # licensed commercial nutrition database (Nutritionix, Edamam)
    USER = "user"  # entered manually by a user
    UNVERIFIED = "unverified"  # crowdsourced / unverifiable (Open Food Facts)


TRUST_RANK = {t: i for i, t in enumerate(Trust)}


def weakest(levels) -> Trust | None:
    levels = [Trust(level) for level in levels if level]
    return max(levels, key=TRUST_RANK.__getitem__) if levels else None


@dataclass(frozen=True)
class NutrientDef:
    code: str
    name: str
    unit: str
    category: str  # energy | macro | lipid | carb | vitamin | mineral | other
    fdc_numbers: tuple[str, ...] = ()
    edamam: str | None = None
    off: str | None = None  # Open Food Facts nutriment key (per 100 g, in grams unless noted)


NUTRIENTS: tuple[NutrientDef, ...] = (
    NutrientDef("energy_kcal", "Energy", "kcal", "energy", ("208", "958", "957"), "ENERC_KCAL", "energy-kcal"),
    NutrientDef("protein_g", "Protein", "g", "macro", ("203",), "PROCNT", "proteins"),
    NutrientDef("fat_g", "Total fat", "g", "macro", ("204",), "FAT", "fat"),
    NutrientDef("carbs_g", "Carbohydrate", "g", "macro", ("205",), "CHOCDF", "carbohydrates"),
    NutrientDef("fiber_g", "Dietary fiber", "g", "carb", ("291",), "FIBTG", "fiber"),
    NutrientDef("sugars_g", "Total sugars", "g", "carb", ("269",), "SUGAR", "sugars"),
    NutrientDef("added_sugars_g", "Added sugars", "g", "carb", ("539",), "SUGAR.added", "added-sugars"),
    NutrientDef("sat_fat_g", "Saturated fat", "g", "lipid", ("606",), "FASAT", "saturated-fat"),
    NutrientDef("mono_fat_g", "Monounsaturated fat", "g", "lipid", ("645",), "FAMS", "monounsaturated-fat"),
    NutrientDef("poly_fat_g", "Polyunsaturated fat", "g", "lipid", ("646",), "FAPU", "polyunsaturated-fat"),
    NutrientDef("trans_fat_g", "Trans fat", "g", "lipid", ("605",), "FATRN", "trans-fat"),
    NutrientDef("cholesterol_mg", "Cholesterol", "mg", "lipid", ("601",), "CHOLE", "cholesterol"),
    NutrientDef("water_g", "Water", "g", "other", ("255",), "WATER"),
    NutrientDef("alcohol_g", "Alcohol", "g", "other", ("221",)),
    NutrientDef("caffeine_mg", "Caffeine", "mg", "other", ("262",)),
    NutrientDef("sodium_mg", "Sodium", "mg", "mineral", ("307",), "NA", "sodium"),
    NutrientDef("potassium_mg", "Potassium", "mg", "mineral", ("306",), "K", "potassium"),
    NutrientDef("calcium_mg", "Calcium", "mg", "mineral", ("301",), "CA", "calcium"),
    NutrientDef("iron_mg", "Iron", "mg", "mineral", ("303",), "FE", "iron"),
    NutrientDef("magnesium_mg", "Magnesium", "mg", "mineral", ("304",), "MG", "magnesium"),
    NutrientDef("phosphorus_mg", "Phosphorus", "mg", "mineral", ("305",), "P"),
    NutrientDef("zinc_mg", "Zinc", "mg", "mineral", ("309",), "ZN", "zinc"),
    NutrientDef("copper_mg", "Copper", "mg", "mineral", ("312",)),
    NutrientDef("manganese_mg", "Manganese", "mg", "mineral", ("315",)),
    NutrientDef("selenium_ug", "Selenium", "µg", "mineral", ("317",)),
    NutrientDef("iodine_ug", "Iodine", "µg", "mineral", ("314",)),
    NutrientDef("vitamin_a_ug", "Vitamin A (RAE)", "µg", "vitamin", ("320",), "VITA_RAE"),
    NutrientDef("vitamin_c_mg", "Vitamin C", "mg", "vitamin", ("401",), "VITC", "vitamin-c"),
    NutrientDef("vitamin_d_ug", "Vitamin D (D2 + D3)", "µg", "vitamin", ("328",), "VITD", "vitamin-d"),
    NutrientDef("vitamin_e_mg", "Vitamin E (alpha-tocopherol)", "mg", "vitamin", ("323",), "TOCPHA"),
    NutrientDef("vitamin_k_ug", "Vitamin K (phylloquinone)", "µg", "vitamin", ("430",), "VITK1"),
    NutrientDef("thiamin_mg", "Thiamin (B1)", "mg", "vitamin", ("404",), "THIA"),
    NutrientDef("riboflavin_mg", "Riboflavin (B2)", "mg", "vitamin", ("405",), "RIBF"),
    NutrientDef("niacin_mg", "Niacin (B3)", "mg", "vitamin", ("406",), "NIA"),
    NutrientDef("pantothenic_mg", "Pantothenic acid (B5)", "mg", "vitamin", ("410",)),
    NutrientDef("vitamin_b6_mg", "Vitamin B6", "mg", "vitamin", ("415",), "VITB6A"),
    NutrientDef("biotin_ug", "Biotin (B7)", "µg", "vitamin", ("416",)),
    NutrientDef("folate_ug_dfe", "Folate (DFE)", "µg", "vitamin", ("435",), "FOLDFE"),
    NutrientDef("vitamin_b12_ug", "Vitamin B12", "µg", "vitamin", ("418",), "VITB12"),
    NutrientDef("choline_mg", "Choline", "mg", "vitamin", ("421",)),
)

BY_CODE = {n.code: n for n in NUTRIENTS}
BY_FDC_NUMBER: dict[str, NutrientDef] = {}
for _n in NUTRIENTS:
    for _num in _n.fdc_numbers:
        BY_FDC_NUMBER.setdefault(_num, _n)
BY_EDAMAM = {n.edamam: n for n in NUTRIENTS if n.edamam}

MACRO_CODES = ("energy_kcal", "protein_g", "fat_g", "carbs_g", "fiber_g", "sugars_g")

# Unit conversion into our canonical units. Ambiguous conversions (vitamin A in IU or
# plain µg, folate in plain µg, vitamin E in IU) are refused: callers keep those values
# as unconverted "other" components rather than silently guessing.
_MASS_TO_G = {"g": 1.0, "mg": 1e-3, "µg": 1e-6}
_UNIT_ALIASES = {
    "gram": "g", "grams": "g", "gram(s)": "g",
    "milligram": "mg", "milligrams": "mg", "milligram(s)": "mg",
    "ug": "µg", "mcg": "µg", "microgram": "µg", "micrograms": "µg", "microgram(s)": "µg",
    "cal": "kcal", "calorie": "kcal", "calories": "kcal", "calorie(s)": "kcal", "{calories}": "kcal",
    "kilojoule": "kj", "kilojoules": "kj", "kilojoule(s)": "kj",
    "mcg dfe": "µg dfe", "ug dfe": "µg dfe", "mcg rae": "µg rae", "ug rae": "µg rae",
}
# Nutrients whose amount depends on chemical form, with the unit that states the form.
FORM_UNITS = {"folate_ug_dfe": "µg dfe", "vitamin_a_ug": "µg rae"}


def normalize_unit(unit: str) -> str:
    u = unit.strip().lower().replace("μ", "µ")
    return _UNIT_ALIASES.get(u, u)


def is_form_ambiguous(unit: str, nutrient: NutrientDef) -> bool:
    """True when ``unit`` can't be converted without knowing the nutrient's chemical form."""
    u = normalize_unit(unit)
    if nutrient.code in FORM_UNITS:
        return u != FORM_UNITS[nutrient.code]
    return u == "iu" and nutrient.code != "vitamin_d_ug"


def convert_amount(value: float, from_unit: str, nutrient: NutrientDef, form_known: bool = False) -> float | None:
    """Convert ``value`` in ``from_unit`` to the nutrient's canonical unit, or None if not safely possible.

    ``form_known`` is true when the source identifies the nutrient form itself (an FDC
    nutrient number such as 435 "Folate, DFE"), so plain mass units are unambiguous.
    """
    unit, target = normalize_unit(from_unit), normalize_unit(nutrient.unit)
    if nutrient.code in FORM_UNITS:
        if unit == FORM_UNITS[nutrient.code]:
            return value
        if not form_known:
            return None
    if unit == "iu":
        return value * 0.025 if nutrient.code == "vitamin_d_ug" else None  # 1 IU vitamin D = 0.025 µg
    if unit == target:
        return value
    if unit == "kj" and target == "kcal":
        return value / 4.184
    if unit in _MASS_TO_G and target in _MASS_TO_G:
        return value * _MASS_TO_G[unit] / _MASS_TO_G[target]
    return None
