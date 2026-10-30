import re
from abc import ABC, abstractmethod
from dataclasses import dataclass, field

import httpx

from app.config import Settings
from app.nutrients import BY_FDC_NUMBER, NutrientDef, Trust, convert_amount


class SourceError(RuntimeError):
    pass


@dataclass
class SearchHit:
    source: str
    source_id: str
    name: str
    brand: str | None
    kind: str
    trust_level: str
    basis: str = "100g"
    data_type: str | None = None
    summary: dict[str, float] = field(default_factory=dict)  # quick macro preview on `basis`
    detail: str | None = None


@dataclass
class ExternalFood:
    source: str
    source_id: str
    name: str
    trust_level: str
    brand: str | None = None
    kind: str = "food"
    state: str | None = None
    cooking_method: str | None = None
    basis: str = "100g"
    serving_quantity: float | None = None
    serving_unit: str | None = None
    serving_size_g: float | None = None
    data_type: str | None = None
    category: str | None = None
    source_url: str | None = None
    citation: str | None = None
    nutrients: dict[str, tuple[float, str | None]] = field(default_factory=dict)  # code -> (amount, derivation)
    portions: list[tuple[str, float]] = field(default_factory=list)  # (label, grams)
    other_components: list[dict] = field(default_factory=list)
    payload: dict | None = None


class DataSource(ABC):
    key: str
    name: str
    description: str
    homepage: str
    trust_level: Trust  # the default (some sources mix levels per record)
    paid: bool = False

    def __init__(self, settings: Settings, client: httpx.Client):
        self.settings = settings
        self.client = client

    @property
    @abstractmethod
    def enabled(self) -> bool: ...

    @property
    def disabled_reason(self) -> str | None:
        return None

    @abstractmethod
    def search(self, query: str, limit: int = 20) -> list[SearchHit]: ...

    @abstractmethod
    def fetch(self, source_id: str, name_hint: str | None = None) -> ExternalFood: ...

    def _get(self, url: str, **kwargs) -> dict:
        return self._request("GET", url, **kwargs)

    def _request(self, method: str, url: str, **kwargs) -> dict:
        try:
            resp = self.client.request(method, url, timeout=self.settings.http_timeout_seconds, **kwargs)
        except httpx.HTTPError as exc:
            raise SourceError(f"{self.name} request failed: {exc}") from exc
        if resp.status_code == 404:
            raise SourceError(f"{self.name}: not found")
        if resp.status_code == 429:
            raise SourceError(f"{self.name}: rate limited, try again later")
        if resp.status_code >= 400:
            raise SourceError(f"{self.name} returned HTTP {resp.status_code}{_upstream_message(resp)}")
        try:
            return resp.json()
        except ValueError as exc:
            raise SourceError(f"{self.name} returned invalid JSON") from exc


def _upstream_message(resp: httpx.Response) -> str:
    """A short reason from the upstream error body, if it has one."""
    try:
        body = resp.json()
    except ValueError:
        return ""
    msg = None
    if isinstance(body, dict):
        err = body.get("error")
        msg = body.get("message") or (err.get("message") if isinstance(err, dict) else err)
    return f": {str(msg)[:200]}" if msg else ""


_COOK_METHODS = (
    "roasted", "boiled", "grilled", "baked", "fried", "pan-fried", "braised", "broiled",
    "steamed", "stewed", "microwaved", "simmered", "poached", "sauteed", "sautéed", "toasted", "scrambled",
)


def guess_state(description: str) -> tuple[str | None, str | None]:
    """Infer (state, cooking_method) from a food description such as 'Chicken, breast, roasted'."""
    text = description.lower()
    for word in _COOK_METHODS:
        if re.search(rf"\b{re.escape(word)}\b", text):
            return "cooked", word
    if re.search(r"\bcooked\b", text):
        return "cooked", None
    if re.search(r"\braw\b", text):
        return "raw", None
    return None, None


def map_numbered_nutrients(rows) -> dict[str, tuple[float, str | None]]:
    """Map (fdc_number, unit, amount, derivation) rows to canonical codes.

    When several numbers map to one code, the one listed first in the catalog wins
    (e.g. energy 208 over Atwater-specific 958 over Atwater-general 957).
    """
    best: dict[str, tuple[int, float, str | None]] = {}
    for number, unit, amount, derivation in rows:
        if amount is None:
            continue
        nutrient: NutrientDef | None = BY_FDC_NUMBER.get(str(number))
        if nutrient is None:
            continue
        value = convert_amount(float(amount), unit or nutrient.unit, nutrient, form_known=True)
        if value is None:
            continue
        rank = nutrient.fdc_numbers.index(str(number))
        if nutrient.code not in best or rank < best[nutrient.code][0]:
            best[nutrient.code] = (rank, value, derivation)
    return {code: (value, derivation) for code, (_, value, derivation) in best.items()}
