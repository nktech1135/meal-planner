"""USDA FoodData Central (https://fdc.nal.usda.gov/). Free; public domain (CC0).

Foundation, SR Legacy and Survey (FNDDS) records are government-analysed or compiled
data. Branded records are manufacturer label data submitted to USDA.
"""

from app.nutrients import MACRO_CODES, Trust
from app.sources.base import DataSource, ExternalFood, SearchHit, guess_state, map_numbered_nutrients, normalize_barcode

BASE = "https://api.nal.usda.gov/fdc/v1"
DATA_TYPES = ["Foundation", "SR Legacy", "Survey (FNDDS)", "Branded"]


def trust_for(data_type: str | None) -> Trust:
    return Trust.LABEL if data_type == "Branded" else Trust.ANALYTICAL


def _portion_label(p: dict) -> str | None:
    desc = (p.get("portionDescription") or "").strip()
    if desc and desc.lower() != "quantity not specified":
        return desc
    unit = (p.get("measureUnit") or {}).get("name") or ""
    if unit.lower() in ("undetermined", "racc"):
        unit = "serving (RACC)" if unit.lower() == "racc" else ""
    parts = [f"{p.get('amount') or 1:g}", unit, p.get("modifier") or ""]
    label = " ".join(x for x in parts if x).strip()
    return label or None


class UsdaFdc(DataSource):
    key = "usda_fdc"
    name = "USDA FoodData Central"
    description = "U.S. government food composition database: lab-analysed foods plus branded label data."
    homepage = "https://fdc.nal.usda.gov/"
    trust_level = Trust.ANALYTICAL

    @property
    def enabled(self) -> bool:
        return bool(self.settings.usda_fdc_api_key)

    def search(self, query: str, limit: int = 20) -> list[SearchHit]:
        data = self._get(
            f"{BASE}/foods/search",
            params={"api_key": self.settings.usda_fdc_api_key, "query": query, "pageSize": limit,
                    "dataType": ",".join(DATA_TYPES)},
        )
        hits = []
        for f in data.get("foods", []):
            rows = [(n.get("nutrientNumber"), n.get("unitName"), n.get("value"), None) for n in f.get("foodNutrients", [])]
            mapped = map_numbered_nutrients(rows)
            data_type = f.get("dataType")
            hits.append(SearchHit(
                source=self.key, source_id=str(f["fdcId"]), name=f.get("description", ""),
                brand=f.get("brandName") or f.get("brandOwner"), kind="food",
                trust_level=trust_for(data_type), data_type=data_type,
                summary={c: round(mapped[c][0], 2) for c in MACRO_CODES if c in mapped},
                detail=f.get("foodCategory") if isinstance(f.get("foodCategory"), str) else None,
            ))
        return hits

    def fetch(self, source_id: str, name_hint: str | None = None) -> ExternalFood:
        f = self._get(f"{BASE}/food/{int(source_id)}", params={"api_key": self.settings.usda_fdc_api_key})
        return parse_fdc_food(f)


def category_of(f: dict) -> str | None:
    cat = f.get("foodCategory") or f.get("wweiaFoodCategory") or f.get("brandedFoodCategory")
    if isinstance(cat, dict):
        return cat.get("description") or cat.get("wweiaFoodCategoryDescription")
    return cat if isinstance(cat, str) else None


def parse_fdc_food(f: dict, release: str | None = None, keep_payload: bool = True) -> ExternalFood:
    """Map one FDC food record (API detail or bulk-download JSON; same shape) to an ExternalFood."""
    data_type = f.get("dataType")
    rows = []
    for n in f.get("foodNutrients", []):
        nut = n.get("nutrient") or {}
        derivation = (n.get("foodNutrientDerivation") or {}).get("description")
        rows.append((nut.get("number"), nut.get("unitName"), n.get("amount"), derivation))
    name = f.get("description", "")
    state, method = guess_state(name)

    portions = []
    for p in f.get("foodPortions", []) or []:
        label, grams = _portion_label(p), p.get("gramWeight")
        if label and grams:
            portions.append((label, float(grams)))
    serving_g = None
    if data_type == "Branded" and f.get("servingSize") and (f.get("servingSizeUnit") or "").lower() in ("g", "grm"):
        serving_g = float(f["servingSize"])
        household = f.get("householdServingFullText")
        portions.append((f"1 serving ({household})" if household else "1 serving", serving_g))

    edition = f"{data_type}, {release} release" if release else data_type
    return ExternalFood(
        source=UsdaFdc.key, source_id=str(f["fdcId"]), name=name,
        brand=f.get("brandName") or f.get("brandOwner"), kind="food", state=state, cooking_method=method,
        basis="100g", serving_size_g=serving_g, serving_quantity=1 if serving_g else None,
        serving_unit="serving" if serving_g else None, data_type=data_type, category=category_of(f),
        barcode=normalize_barcode(f.get("gtinUpc")), ingredients=(f.get("ingredients") or None),
        trust_level=trust_for(data_type), source_url=f"https://fdc.nal.usda.gov/food-details/{f['fdcId']}/nutrients",
        citation=f"U.S. Department of Agriculture, Agricultural Research Service. FoodData Central ({edition}), "
                 f"FDC ID {f['fdcId']}.",
        nutrients=map_numbered_nutrients(rows), portions=portions, payload=f if keep_payload else None,
    )


def find_barcode(source: UsdaFdc, code: str) -> ExternalFood | None:
    """Look a barcode up in FDC's Branded foods (online)."""
    data = source._get(f"{BASE}/foods/search", params={"api_key": source.settings.usda_fdc_api_key, "query": code,
                                                       "dataType": "Branded", "pageSize": 10})
    for f in data.get("foods", []):
        if normalize_barcode(f.get("gtinUpc")) == code:
            return source.fetch(str(f["fdcId"]))
    return None
