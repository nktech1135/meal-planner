"""Nutritionix Track API v2 (https://www.nutritionix.com/business/api). Paid, licensed.

Implemented from the public v2 documentation; requires NUTRITIONIX_APP_ID/KEY.
``full_nutrients`` uses USDA nutrient numbers (``attr_id``) on a per-serving basis.
Check your licence terms before caching/sharing records across users.
"""

from app.nutrients import BY_FDC_NUMBER, Trust
from app.sources.base import DataSource, ExternalFood, SearchHit, SourceError, guess_state, map_numbered_nutrients

BASE = "https://trackapi.nutritionix.com/v2"


class Nutritionix(DataSource):
    key = "nutritionix"
    name = "Nutritionix"
    description = "Commercial database of restaurant, branded and common foods (licensed API)."
    homepage = "https://www.nutritionix.com/business/api"
    trust_level = Trust.COMMERCIAL
    paid = True

    @property
    def enabled(self) -> bool:
        return bool(self.settings.nutritionix_app_id and self.settings.nutritionix_app_key)

    @property
    def disabled_reason(self) -> str | None:
        return None if self.enabled else "Set NUTRITIONIX_APP_ID and NUTRITIONIX_APP_KEY"

    @property
    def _headers(self) -> dict:
        return {"x-app-id": self.settings.nutritionix_app_id or "", "x-app-key": self.settings.nutritionix_app_key or "",
                "x-remote-user-id": "0"}

    def search(self, query: str, limit: int = 20) -> list[SearchHit]:
        data = self._get(f"{BASE}/search/instant", params={"query": query}, headers=self._headers)
        hits = []
        for c in (data.get("common") or [])[: limit // 2 or 1]:
            hits.append(SearchHit(self.key, f"common:{c['food_name']}", c["food_name"], None, "food",
                                  Trust.COMMERCIAL, detail="Common food"))
        for b in (data.get("branded") or [])[:limit]:
            summary = {"energy_kcal": b["nf_calories"]} if b.get("nf_calories") is not None else {}
            hits.append(SearchHit(self.key, f"branded:{b['nix_item_id']}", b["food_name"], b.get("brand_name"),
                                  "food", Trust.COMMERCIAL, basis="serving", summary=summary,
                                  detail=f"{b.get('serving_qty', '')} {b.get('serving_unit', '')}".strip() or None))
        return hits[:limit]

    def fetch(self, source_id: str, name_hint: str | None = None) -> ExternalFood:
        kind, _, ident = source_id.partition(":")
        if kind == "common":
            data = self._request("POST", f"{BASE}/natural/nutrients", json={"query": ident}, headers=self._headers)
        elif kind == "branded":
            data = self._get(f"{BASE}/search/item", params={"nix_item_id": ident}, headers=self._headers)
        else:
            raise SourceError("Unknown Nutritionix id")
        foods = data.get("foods") or []
        if not foods:
            raise SourceError("Nutritionix: not found")
        f = foods[0]
        rows = [(n["attr_id"], BY_FDC_NUMBER[str(n["attr_id"])].unit if str(n["attr_id"]) in BY_FDC_NUMBER else None,
                 n.get("value"), "Nutritionix") for n in f.get("full_nutrients") or []]
        per_serving = map_numbered_nutrients(rows)
        grams = f.get("serving_weight_grams")
        serving_label = f"{f.get('serving_qty', 1):g} {f.get('serving_unit', 'serving')}"
        if grams:
            nutrients = {k: (v * 100 / grams, d) for k, (v, d) in per_serving.items()}
            basis = "100g"
        else:
            nutrients, basis = per_serving, "serving"
        portions = [(serving_label, float(grams))] if grams else []
        for m in f.get("alt_measures") or []:
            if m.get("serving_weight") and m.get("measure"):
                portions.append((f"{m.get('qty', 1):g} {m['measure']}", float(m["serving_weight"])))
        state, method = guess_state(f.get("food_name", ""))
        return ExternalFood(
            source=self.key, source_id=source_id, name=f.get("food_name", name_hint or ""), brand=f.get("brand_name"),
            state=state, cooking_method=method, basis=basis, serving_quantity=f.get("serving_qty"),
            serving_unit=f.get("serving_unit"), serving_size_g=grams, data_type="Branded" if kind == "branded" else "Common",
            trust_level=Trust.COMMERCIAL, source_url="https://www.nutritionix.com/",
            citation=f"Nutritionix database ({'branded item ' + ident if kind == 'branded' else 'common food'}).",
            nutrients=nutrients, portions=portions, payload=f,
        )
