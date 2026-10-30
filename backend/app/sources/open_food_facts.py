"""Open Food Facts (https://world.openfoodfacts.org/). Free, crowdsourced (ODbL).

Anyone can edit these records and values are not checked against a lab or the
label, so this source is OFF unless ENABLE_UNVERIFIED_SOURCES=true and every record
is stored with trust level "unverified".
"""

from app.nutrients import NUTRIENTS, Trust, convert_amount
from app.sources.base import DataSource, ExternalFood, SearchHit, normalize_barcode

BASE = "https://world.openfoodfacts.org"
FIELDS = "code,product_name,brands,nutriments,serving_size,serving_quantity,ingredients_text"


def _map(nutriments: dict) -> dict[str, tuple[float, str | None]]:
    out = {}
    for n in NUTRIENTS:
        if not n.off:
            continue
        value = nutriments.get(f"{n.off}_100g")
        if value in (None, ""):
            continue
        try:
            value = float(value)
        except (TypeError, ValueError):
            continue
        # OFF normalises *_100g values to grams, except energy-kcal.
        converted = value if n.code == "energy_kcal" else convert_amount(value, "g", n, form_known=True)
        if converted is not None:
            out[n.code] = (converted, "Crowdsourced")
    return out


class OpenFoodFacts(DataSource):
    key = "open_food_facts"
    name = "Open Food Facts"
    description = "Crowdsourced packaged-food database. Unverified: anyone can edit entries."
    homepage = BASE
    trust_level = Trust.UNVERIFIED

    @property
    def enabled(self) -> bool:
        return self.settings.enable_unverified_sources

    @property
    def disabled_reason(self) -> str | None:
        return None if self.enabled else "Unverified source; set ENABLE_UNVERIFIED_SOURCES=true to allow"

    @property
    def _headers(self) -> dict:
        return {"User-Agent": self.settings.user_agent}

    def search(self, query: str, limit: int = 20) -> list[SearchHit]:
        data = self._get(
            f"{BASE}/cgi/search.pl",
            params={"search_terms": query, "search_simple": 1, "json": 1, "page_size": limit, "fields": FIELDS},
            headers=self._headers,
        )
        hits = []
        for p in data.get("products", []):
            if not p.get("code"):
                continue
            mapped = _map(p.get("nutriments") or {})
            hits.append(SearchHit(
                self.key, p["code"], p.get("product_name") or p["code"], p.get("brands"), "food", Trust.UNVERIFIED,
                summary={k: round(v, 2) for k, (v, _) in mapped.items() if k in ("energy_kcal", "protein_g", "fat_g", "carbs_g")},
                detail="Crowdsourced — unverified",
            ))
        return hits

    def fetch(self, source_id: str, name_hint: str | None = None) -> ExternalFood:
        data = self._get(f"{BASE}/api/v2/product/{source_id}", params={"fields": FIELDS}, headers=self._headers)
        p = data.get("product") or {}
        grams = p.get("serving_quantity")
        try:
            grams = float(grams) if grams else None
        except (TypeError, ValueError):
            grams = None
        portions = [(f"1 serving ({p.get('serving_size')})" if p.get("serving_size") else "1 serving", grams)] if grams else []
        return ExternalFood(
            source=self.key, source_id=source_id, name=p.get("product_name") or name_hint or source_id,
            brand=p.get("brands"), basis="100g", serving_size_g=grams, serving_quantity=1 if grams else None,
            serving_unit="serving" if grams else None, data_type="Crowdsourced product",
            trust_level=Trust.UNVERIFIED, source_url=f"{BASE}/product/{source_id}",
            citation=f"Open Food Facts product {source_id} (crowdsourced, ODbL). Not verified.",
            barcode=normalize_barcode(source_id), ingredients=p.get("ingredients_text") or None,
            nutrients=_map(p.get("nutriments") or {}), portions=portions, payload=p,
        )


def find_barcode(source: OpenFoodFacts, code: str) -> ExternalFood | None:
    data = source._get(f"{BASE}/api/v2/product/{code}", params={"fields": FIELDS}, headers=source._headers)
    if data.get("status") != 1 or not (data.get("product") or {}).get("product_name"):
        return None
    return source.fetch(code)
