"""NIH Office of Dietary Supplements — Dietary Supplement Label Database (https://dsld.od.nih.gov/).

Free. Records are transcriptions of manufacturers' label declarations; FDA does not
verify supplement contents before sale, so these are flagged as label data.
"""

from app.nutrients import BY_CODE, Trust, convert_amount
from app.sources.base import DataSource, ExternalFood, SearchHit

BASE = "https://api.ods.od.nih.gov/dsld/v9"

# DSLD ingredient group / name (lowercased) -> canonical nutrient code
_NAME_MAP = {
    "calories": "energy_kcal",
    "total fat": "fat_g", "fat (unspecified)": "fat_g", "fat": "fat_g",
    "saturated fat": "sat_fat_g", "trans fat": "trans_fat_g", "cholesterol": "cholesterol_mg",
    "protein": "protein_g",
    "total carbohydrates": "carbs_g", "total carbohydrate": "carbs_g", "carbohydrate": "carbs_g",
    "dietary fiber": "fiber_g", "fiber (unspecified)": "fiber_g",
    "sugar": "sugars_g", "sugars": "sugars_g", "total sugars": "sugars_g", "added sugars": "added_sugars_g",
    "vitamin a": "vitamin_a_ug", "vitamin c": "vitamin_c_mg", "vitamin d": "vitamin_d_ug",
    "vitamin e": "vitamin_e_mg", "vitamin k": "vitamin_k_ug",
    "thiamin": "thiamin_mg", "vitamin b1": "thiamin_mg", "riboflavin": "riboflavin_mg", "vitamin b2": "riboflavin_mg",
    "niacin": "niacin_mg", "vitamin b3": "niacin_mg", "vitamin b6": "vitamin_b6_mg",
    "folate": "folate_ug_dfe", "folic acid": "folate_ug_dfe", "vitamin b12": "vitamin_b12_ug",
    "biotin": "biotin_ug", "pantothenic acid": "pantothenic_mg", "choline": "choline_mg",
    "calcium": "calcium_mg", "iron": "iron_mg", "magnesium": "magnesium_mg", "zinc": "zinc_mg",
    "selenium": "selenium_ug", "copper": "copper_mg", "manganese": "manganese_mg", "iodine": "iodine_ug",
    "potassium": "potassium_mg", "sodium": "sodium_mg", "phosphorus": "phosphorus_mg",
}
_SKIP = {"calories from fat"}


def _flatten(rows: list[dict]):
    for row in rows or []:
        yield row
        yield from _flatten(row.get("nestedRows") or [])


def _amount_for_serving(row: dict, serving_order: int = 1) -> dict | None:
    quantities = row.get("quantity") or []
    return next((q for q in quantities if q.get("servingSizeOrder") == serving_order), quantities[0] if quantities else None)


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
        code = _NAME_MAP.get((row.get("ingredientGroup") or "").lower()) or _NAME_MAP.get(name.lower())
        value = convert_amount(amount, unit, BY_CODE[code]) if code else None
        if code and value is not None and code not in nutrients and operator == "=":
            nutrients[code] = (value, "Label declaration")
            continue
        entry = {"name": name, "amount": amount, "unit": unit}
        if code and value is None:
            entry["note"] = f"not converted to {BY_CODE[code].unit}: unit '{unit}' is ambiguous for this nutrient"
        elif operator != "=":
            entry["note"] = f"declared as '{operator} {amount:g} {unit}'"
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
