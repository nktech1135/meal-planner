"""NIH Office of Dietary Supplements — Dietary Supplement Label Database (https://dsld.od.nih.gov/).

Free. Records are transcriptions of manufacturers' label declarations; FDA does not
verify supplement contents before sale, so these are flagged as label data.
"""

import re

from app.nutrients import BY_CODE, Trust, convert_amount, is_form_ambiguous
from app.sources.base import DataSource, ExternalFood, SearchHit

BASE = "https://api.ods.od.nih.gov/dsld/v9"

# Nutrient name (normalised, see _key) -> canonical nutrient code. Rows are matched on
# their own name, not their ingredient group, because a row named after a compound
# ("Magnesium Glycinate 2 g", "D-Alpha-Tocopheryl Acetate 143 mg") declares the mass
# of the compound, not of the nutrient.
_NAME_MAP = {
    "calories": "energy_kcal",
    "total fat": "fat_g", "fat": "fat_g",
    "saturated fat": "sat_fat_g", "trans fat": "trans_fat_g", "cholesterol": "cholesterol_mg",
    "protein": "protein_g",
    "total carbohydrates": "carbs_g", "total carbohydrate": "carbs_g", "carbohydrate": "carbs_g",
    "carbohydrates": "carbs_g",
    "dietary fiber": "fiber_g", "fiber": "fiber_g",
    "sugar": "sugars_g", "sugars": "sugars_g", "total sugars": "sugars_g", "added sugars": "added_sugars_g",
    "vitamin a": "vitamin_a_ug", "vitamin c": "vitamin_c_mg",
    "vitamin d": "vitamin_d_ug", "vitamin d3": "vitamin_d_ug", "vitamin d2": "vitamin_d_ug",
    "vitamin e": "vitamin_e_mg", "vitamin k": "vitamin_k_ug", "vitamin k1": "vitamin_k_ug",
    "thiamin": "thiamin_mg", "thiamine": "thiamin_mg", "vitamin b1": "thiamin_mg",
    "riboflavin": "riboflavin_mg", "vitamin b2": "riboflavin_mg",
    "niacin": "niacin_mg", "vitamin b3": "niacin_mg", "vitamin b6": "vitamin_b6_mg",
    "folate": "folate_ug_dfe", "folic acid": "folate_ug_dfe", "vitamin b12": "vitamin_b12_ug",
    "biotin": "biotin_ug", "pantothenic acid": "pantothenic_mg", "vitamin b5": "pantothenic_mg", "choline": "choline_mg",
    "calcium": "calcium_mg", "iron": "iron_mg", "magnesium": "magnesium_mg", "zinc": "zinc_mg",
    "selenium": "selenium_ug", "copper": "copper_mg", "manganese": "manganese_mg", "iodine": "iodine_ug",
    "potassium": "potassium_mg", "sodium": "sodium_mg", "phosphorus": "phosphorus_mg", "phosphorous": "phosphorus_mg",
}
_SKIP = {"calories from fat"}

# FDA Daily Values (21 CFR 101.9 / 101.36) in canonical units: (current, pre-2016).
# Used only to sanity-check a label amount against the %DV printed next to it.
_DAILY_VALUES = {
    "vitamin_a_ug": (900, 1500), "vitamin_c_mg": (90, 60), "vitamin_d_ug": (20, 10), "vitamin_e_mg": (15, 20),
    "vitamin_k_ug": (120, 80), "thiamin_mg": (1.2, 1.5), "riboflavin_mg": (1.3, 1.7), "niacin_mg": (16, 20),
    "vitamin_b6_mg": (1.7, 2), "folate_ug_dfe": (400, 400), "vitamin_b12_ug": (2.4, 6), "biotin_ug": (30, 300),
    "pantothenic_mg": (5, 10), "choline_mg": (550, 550), "calcium_mg": (1300, 1000), "iron_mg": (18, 18),
    "phosphorus_mg": (1250, 1000), "iodine_ug": (150, 150), "magnesium_mg": (420, 400), "zinc_mg": (11, 15),
    "selenium_ug": (55, 70), "copper_mg": (0.9, 2), "manganese_mg": (2.3, 2), "potassium_mg": (4700, 3500),
    "sodium_mg": (2300, 2400), "fat_g": (78, 65), "sat_fat_g": (20, 20), "cholesterol_mg": (300, 300),
    "carbs_g": (275, 300), "fiber_g": (28, 25), "protein_g": (50, 50), "added_sugars_g": (50, 50),
}


def _key(text: str | None) -> str:
    """'Vitamin D (cholecalciferol)' -> 'vitamin d'; 'Vit. B-12' -> 'vitamin b12'; 'Saturated {Fat}' -> 'saturated fat'."""
    text = re.sub(r"\s*\(.*?\)", "", text or "")
    text = re.sub(r"[{}]", "", text).strip().lower()
    text = re.sub(r"^vit\.?\s+", "vitamin ", text)
    return re.sub(r"^(vitamin [a-z])[- ](\d+)$", r"\1\2", text)


def _flatten(rows: list[dict]):
    for row in rows or []:
        yield row
        yield from _flatten(row.get("nestedRows") or [])


def _amount_for_serving(row: dict, serving_order: int = 1) -> dict | None:
    quantities = row.get("quantity") or []
    return next((q for q in quantities if q.get("servingSizeOrder") == serving_order), quantities[0] if quantities else None)


def _dv_mismatch(code: str, value: float, quantity: dict) -> str | None:
    """Explain why ``value`` contradicts the label's own %DV, or None if consistent/unknown."""
    dvs = _DAILY_VALUES.get(code)
    percent = next((g.get("percent") for g in quantity.get("dailyValueTargetGroup") or [] if g.get("percent")), None)
    if not dvs or not percent or percent < 2:  # tiny percentages are too rounded to check
        return None
    implied = [percent / 100 * dv for dv in dvs]
    if any(0.2 <= value / i <= 5 for i in implied):
        return None
    unit = BY_CODE[code].unit
    lo, hi = min(implied), max(implied)
    expected = f"{lo:.3g}" if f"{lo:.3g}" == f"{hi:.3g}" else f"{lo:.3g}–{hi:.3g}"
    return (f"amount contradicts the label's {percent:g}% DV (≈{expected} {unit}); "
            "probably a unit error in the database record — not counted, check the physical label")


def parse_label(label: dict) -> tuple[dict, list[dict], list[str]]:
    """Return (nutrients {code: (amount, derivation)}, other_components, notes) per label serving."""
    nutrients: dict[str, tuple[float, str | None]] = {}
    others: list[dict] = []
    notes: list[str] = []
    for row in _flatten(label.get("ingredientRows")):
        name = (row.get("name") or "").strip()
        if name.lower() in _SKIP:
            continue
        q = _amount_for_serving(row)
        if not q or q.get("quantity") in (None, 0):
            if name:
                others.append({"name": name, "amount": None, "unit": None, "note": "no amount declared"})
            continue
        amount, unit = float(q["quantity"]), (q.get("unit") or "").strip()
        operator = q.get("operator") or "="
        code = _NAME_MAP.get(_key(name))
        value = convert_amount(amount, unit, BY_CODE[code]) if code else None
        mismatch = _dv_mismatch(code, value, q) if code and value is not None else None
        if code and value is not None and not mismatch and code not in nutrients and operator == "=":
            nutrients[code] = (value, "Label declaration")
            continue
        entry = {"name": name, "amount": amount, "unit": unit}
        if mismatch:
            entry["note"] = mismatch
            notes.append(f"{name}: {mismatch}.")
        elif code and value is None:
            reason = "depends on the nutrient's chemical form" if is_form_ambiguous(unit, BY_CODE[code]) else "unrecognised unit"
            entry["note"] = f"not converted to {BY_CODE[code].unit}: '{unit}' {reason}"
        elif operator != "=":
            entry["note"] = f"declared as '{operator} {amount:g} {unit}'"
        elif code in nutrients:
            entry["note"] = "repeats a nutrient already counted for this label"
        elif not code and _NAME_MAP.get(group := _key(row.get("ingredientGroup"))):
            entry["note"] = f"source/form of {group}; mass is of the compound, not counted as the nutrient"
        others.append(entry)
    if label.get("offMarket"):
        notes.append("Product is marked off-market in DSLD.")
    return nutrients, others, notes


class NihDsld(DataSource):
    key = "nih_dsld"
    name = "NIH Dietary Supplement Label Database"
    description = "Supplement label contents catalogued by the NIH Office of Dietary Supplements."
    homepage = "https://dsld.od.nih.gov/"
    trust_level = Trust.LABEL

    @property
    def enabled(self) -> bool:
        return self.settings.nih_dsld_enabled

    def search(self, query: str, limit: int = 20) -> list[SearchHit]:
        data = self._get(f"{BASE}/search-filter", params={"q": query, "size": limit})
        hits = []
        for h in data.get("hits", []):
            src = h.get("_source") or {}
            form = (src.get("physicalState") or {}).get("langualCodeDescription")
            detail = ", ".join(x for x in [form, "off-market" if src.get("offMarket") else None] if x) or None
            hits.append(SearchHit(
                source=self.key, source_id=str(h["_id"]), name=src.get("fullName", ""), brand=src.get("brandName"),
                kind="supplement", trust_level=Trust.LABEL, basis="serving", detail=detail,
            ))
        return hits

    def fetch(self, source_id: str, name_hint: str | None = None) -> ExternalFood:
        label = self._get(f"{BASE}/label/{int(source_id)}")
        nutrients, others, notes = parse_label(label)
        serving = (label.get("servingSizes") or [{}])[0]
        citation = (
            f"NIH Office of Dietary Supplements, Dietary Supplement Label Database, label {label['id']}. "
            "Values are the manufacturer's label declarations." + (" " + " ".join(notes) if notes else "")
        )
        return ExternalFood(
            source=self.key, source_id=str(label["id"]), name=label.get("fullName") or name_hint or "",
            brand=label.get("brandName"), kind="supplement", basis="serving",
            serving_quantity=serving.get("minQuantity") or 1, serving_unit=serving.get("unit") or "serving",
            data_type="Supplement label", trust_level=Trust.LABEL,
            source_url=f"https://dsld.od.nih.gov/label/{label['id']}", citation=citation,
            nutrients=nutrients, other_components=others, payload=label,
        )
