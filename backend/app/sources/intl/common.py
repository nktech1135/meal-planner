"""Shared helpers for national food composition databases.

Databases differ in how they define some nutrients. We only map a component onto one of
our nutrients when the definitions match, or derive ours from components that are given:

- Energy: kcal is used as published; when only kJ is given, kcal = kJ / 4.184.
- Carbohydrate: ours is USDA-style total carbohydrate (by difference, includes fibre).
  "Available carbohydrate" (excludes fibre) is converted by adding total dietary fibre
  when both are present; otherwise it isn't mapped.
- Vitamin A: ours is RAE (retinol activity equivalents). Retinol *equivalents* (RE) use a
  different carotene factor, so they are not mapped. RAE is computed from retinol and
  beta-carotene (1/12) when those are given.
- Vitamin E: ours is alpha-tocopherol; alpha-tocopherol *equivalents* (TE) also count
  other tocopherols, so TE is not mapped.
- Folate: total folate in foods without added folic acid equals DFE; it is mapped with
  that caveat recorded on the value.

Values below a detection limit or reported as trace are stored as 0 with the reason
recorded; "not determined"/missing values are left out (unknown, not zero).
"""

import re
from collections.abc import Iterable

from app.nutrients import BY_CODE, convert_amount
from app.sources.base import ExternalFood, guess_state

KCAL_PER_KJ = 1 / 4.184

# Text the databases use for "no value": unknown, not zero.
MISSING = {"", "-", "n", "n.d.", "nd", "null", "na", "n/a", "…", "...", "?"}
TRACE = {"tr", "tr.", "trace", "traces", "trace(s)"}


def parse_value(raw) -> tuple[float | None, str | None]:
    """Parse a published value into (number, note).

    Returns (None, None) for missing, (0.0, "trace") for traces, (0.0, "below limit <x")
    for values under a detection/quantification limit, (x, "estimate") for bracketed
    estimates, and handles decimal commas and padding.
    """
    if raw is None:
        return None, None
    if isinstance(raw, (int, float)):
        return float(raw), None
    text = str(raw).strip().replace(" ", " ")
    low = text.lower()
    if low in MISSING:
        return None, None
    if low in TRACE:
        return 0.0, "trace"
    if low.startswith("<"):
        limit = text.lstrip("<").strip()
        return 0.0, f"below limit ({'<' + limit if limit else 'not quantified'})"
    estimate = text.startswith("(") and text.endswith(")")
    if estimate:
        text = text[1:-1]
    text = text.replace(" ", "")
    if "," in text and "." not in text:
        text = text.replace(",", ".")
    try:
        return float(text), "estimate" if estimate else None
    except ValueError:
        return None, None


def unit_in(header: str) -> str | None:
    """'Protein (g)' / 'Iron (Fe) \\n(mg)' / 'VITC Vitamin C [mg/100g]' -> 'g' / 'mg' / 'mg'."""
    m = re.findall(r"[(\[]\s*([a-zA-Zµμ]+)\s*(?:/\s*100\s*(?:g|ml|mL))?\s*[)\]]", header)
    return m[-1].replace("ug", "µg").replace("μ", "µ") if m else None


class Components:
    """Collects one food's components by our nutrient code or by a special key, then derives
    the canonical set. Special keys: energy_kj, available_carbs_g, retinol_ug, beta_carotene_ug."""

    SPECIAL = {"energy_kj", "available_carbs_g", "retinol_ug", "beta_carotene_ug"}

    def __init__(self, derivation: str):
        self.derivation = derivation
        self.values: dict[str, tuple[float, str | None]] = {}

    def add(self, key: str, raw, unit: str | None = None, note: str | None = None) -> None:
        """Add a value given in ``unit`` (converted to our unit); first value for a key wins."""
        value, flag = parse_value(raw)
        if value is None or key in self.values:
            return
        if key not in self.SPECIAL:
            nutrient = BY_CODE[key]
            if unit is not None:
                value = convert_amount(value, unit, nutrient, form_known=True)
                if value is None:
                    return
        reason = "; ".join(x for x in (self.derivation, note, flag) if x)
        self.values[key] = (value, reason or None)

    def nutrients(self) -> dict[str, tuple[float, str | None]]:
        out = {k: v for k, v in self.values.items() if k not in self.SPECIAL}
        kj = self.values.get("energy_kj")
        if "energy_kcal" not in out and kj is not None:
            out["energy_kcal"] = (kj[0] * KCAL_PER_KJ, f"{self.derivation}; converted from kJ")
        avail = self.values.get("available_carbs_g")
        fibre = out.get("fiber_g")
        if "carbs_g" not in out and avail is not None and fibre is not None:
            out["carbs_g"] = (avail[0] + fibre[0], f"{self.derivation}; available carbohydrate + fibre")
        retinol, carotene = self.values.get("retinol_ug"), self.values.get("beta_carotene_ug")
        if "vitamin_a_ug" not in out and retinol is not None and carotene is not None:
            out["vitamin_a_ug"] = (retinol[0] + carotene[0] / 12,
                                   f"{self.derivation}; RAE = retinol + beta-carotene/12")
        return out


def make_food(*, source: str, source_id: str, name: str, data_type: str, citation: str,
              components: Components, category: str | None = None, source_url: str | None = None,
              portions: Iterable[tuple[str, float]] = (), trust_level: str = "analytical") -> ExternalFood:
    state, method = guess_state(name)
    return ExternalFood(
        source=source, source_id=str(source_id), name=name.strip(), trust_level=trust_level, kind="food",
        state=state, cooking_method=method, basis="100g", data_type=data_type, category=category,
        source_url=source_url, citation=citation, nutrients=components.nutrients(), portions=list(portions),
    )
