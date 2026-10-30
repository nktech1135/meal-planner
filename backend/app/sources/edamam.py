"""Edamam Food Database API v2 (https://developer.edamam.com/food-database-api). Paid tiers.

Implemented from the public v2 documentation; requires EDAMAM_APP_ID/KEY.
Nutrient values are per 100 g. Check your licence terms before caching records.
"""

from app.nutrients import BY_EDAMAM, Trust, convert_amount
from app.sources.base import DataSource, ExternalFood, SearchHit, SourceError, guess_state

BASE = "https://api.edamam.com/api/food-database/v2"
GRAM_URI = "http://www.edamam.com/ontologies/edamam.owl#Measure_gram"


def _map(nutrients: dict, with_units: bool) -> dict[str, tuple[float, str | None]]:
    out = {}
    for key, raw in (nutrients or {}).items():
        nutrient = BY_EDAMAM.get(key)
        if nutrient is None:
            continue
        amount, unit = (raw.get("quantity"), raw.get("unit")) if with_units else (raw, nutrient.unit)
        if amount is None:
            continue
        value = convert_amount(float(amount), unit or nutrient.unit, nutrient, form_known=True)
        if value is not None:
            out[nutrient.code] = (value, "Edamam")
    return out


class Edamam(DataSource):
    key = "edamam"
    name = "Edamam Food Database"
    description = "Commercial food and branded-product database (licensed API)."
    homepage = "https://developer.edamam.com/food-database-api"
    trust_level = Trust.COMMERCIAL
    paid = True

    @property
    def enabled(self) -> bool:
        return bool(self.settings.edamam_app_id and self.settings.edamam_app_key)

    @property
    def disabled_reason(self) -> str | None:
        return None if self.enabled else "Set EDAMAM_APP_ID and EDAMAM_APP_KEY"

    @property
    def _auth(self) -> dict:
        return {"app_id": self.settings.edamam_app_id, "app_key": self.settings.edamam_app_key}

    def search(self, query: str, limit: int = 20) -> list[SearchHit]:
        data = self._get(f"{BASE}/parser", params={**self._auth, "ingr": query, "nutrition-type": "cooking"})
        hits = []
        for h in (data.get("hints") or [])[:limit]:
            f = h.get("food") or {}
            mapped = _map(f.get("nutrients"), with_units=False)
            hits.append(SearchHit(
                self.key, f["foodId"], f.get("label", ""), f.get("brand"), "food", Trust.COMMERCIAL,
                summary={k: round(v, 2) for k, (v, _) in mapped.items()}, detail=f.get("category"),
            ))
        return hits

    def fetch(self, source_id: str, name_hint: str | None = None) -> ExternalFood:
        data = self._request(
            "POST", f"{BASE}/nutrients", params=self._auth,
            json={"ingredients": [{"quantity": 100, "measureURI": GRAM_URI, "foodId": source_id}]},
        )
        if not data.get("totalNutrients"):
            raise SourceError("Edamam: no nutrient data for that food")
        parsed = ((data.get("ingredients") or [{}])[0].get("parsed") or [{}])[0]
        name = parsed.get("food") or name_hint or source_id
        state, method = guess_state(name)
        return ExternalFood(
            source=self.key, source_id=source_id, name=name, state=state, cooking_method=method, basis="100g",
            data_type="Food", trust_level=Trust.COMMERCIAL, source_url=self.homepage,
            citation=f"Edamam Food Database, food {source_id}.",
            nutrients=_map(data["totalNutrients"], with_units=True), payload=data,
        )
