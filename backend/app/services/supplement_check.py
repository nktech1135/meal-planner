"""Supplement check: would a product add anything that food and other supplements don't already provide?

A product's daily dose is compared, nutrient by nutrient, with the user's average intake over recent
logged days (from food and from their other supplements, separately) and with their reference intakes
and upper limits. Upper limits that apply only to supplemental forms (magnesium, folic acid, niacin,
vitamin E, preformed vitamin A) are checked against supplement intake, as on the day view.

Ingredients without a reference intake (botanicals, amino acids, probiotics…) are listed and matched
against the user's other supplements, but not judged: there is no requirement to compare them with.

The result compares amounts. It can't know about a diagnosed deficiency, absorption problems,
medications or a clinician's advice, and it says so.
"""

import re
from datetime import date, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Food, LogEntry, User
from app.nutrients import BY_CODE
from app.services.access import form_factors, visible
from app.services.nutrition import NutritionError, food_nutrition
from app.services.summary import entries_between, local_date, local_today
from app.services.targets import compute_targets

MIN_LOGGED_DAYS = 3  # fewer than this: low confidence
LOW_ENERGY_SHARE = 0.6  # average logged energy below this share of the energy target suggests missed entries
LOW_COVERAGE = 0.7  # food records reporting a nutrient, by share of logged food energy
MINOR_SHARE = 0.1  # a dose under 10% of the reference intake is too small to matter either way
# Reported but not judged for need: energy and macronutrient ranges aren't what a supplement is for.
NOT_JUDGED = {"energy_kcal", "fat_g", "carbs_g", "sugars_g", "added_sugars_g", "sat_fat_g", "mono_fat_g",
              "poly_fat_g", "trans_fat_g", "cholesterol_mg", "water_g", "alcohol_g", "caffeine_mg", "sodium_mg"}
GAP = ("closes_gap", "narrows_gap")
COVERED = ("covered_by_food", "covered_by_supplements")
ORDER = ["over_limit", "closes_gap", "narrows_gap", "partial", "covered_by_supplements", "covered_by_food", "minor",
         "no_reference", "info"]

CAVEATS = [
    "This compares amounts with reference intakes for healthy adults. It can't account for a diagnosed "
    "deficiency, absorption problems, medications, or advice from your doctor or dietitian.",
    "Food intake is the average of the days you logged; days you didn't log aren't counted.",
]


class Intake:
    """Average daily intake over the logged days in a window, split into food and each supplement."""

    def __init__(self, user: User, entries: list[LogEntry], foods: dict[int, Food]):
        self.days = sorted({local_date(user, e.consumed_at) for e in entries if not e.is_supplement})
        logged = set(self.days)
        n = len(self.days) or 1
        self.food: dict[str, float] = {}
        self.food_energy = 0.0
        self.energy_with: dict[str, float] = {}  # food energy from entries that report each nutrient
        self.supplements: dict[str, dict] = {}
        for e in entries:
            d = local_date(user, e.consumed_at)
            if d not in logged:
                continue  # a supplement on a day with no food logged: the day itself wasn't logged
            if not e.is_supplement:
                kcal = e.nutrients.get("energy_kcal", 0.0)
                self.food_energy += kcal
                for code, value in e.nutrients.items():
                    self.food[code] = self.food.get(code, 0.0) + value / n
                    self.energy_with[code] = self.energy_with.get(code, 0.0) + kcal
                continue
            key = f"food:{e.food_id}" if e.food_id else f"label:{e.label}"
            s = self.supplements.setdefault(key, {"food_id": e.food_id, "label": e.label, "days": set(), "servings": 0.0,
                                                  "nutrients": {}, "components": {}})
            s["days"].add(d)
            s["servings"] += _servings(e, foods.get(e.food_id))
            for code, value in e.nutrients.items():
                s["nutrients"][code] = s["nutrients"].get(code, 0.0) + value / n
            for c in e.other_components or []:
                if c.get("amount") is not None:
                    k = (_norm(c["name"]), c.get("unit") or "")
                    prev = s["components"].get(k, {"name": c["name"], "unit": c.get("unit"), "amount": 0.0})
                    s["components"][k] = {**prev, "amount": prev["amount"] + c["amount"] / n}

    def coverage(self, code: str) -> float | None:
        """Share of logged food energy from records that report this nutrient (None if no food energy)."""
        if self.food_energy <= 0:
            return None
        return min(1.0, self.energy_with.get(code, 0.0) / self.food_energy)

    def typical_servings(self, food_id: int) -> float | None:
        s = self.supplements.get(f"food:{food_id}")
        if not s or not s["days"]:
            return None
        return round(s["servings"] / len(s["days"]), 2) or None


def _servings(e: LogEntry, food: Food | None) -> float:
    if e.unit == "serving":
        return e.quantity
    if e.unit == "unit" and food is not None:
        return e.quantity / (food.serving_quantity or 1)
    return 1.0  # grams or a portion: count it as one dose


def _norm(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", name.lower()).strip()


def window(user: User, days: int, today: date | None = None) -> tuple[date, date]:
    """The ``days`` days before today; today is usually only partly logged, so it's left out."""
    today = today or local_today(user)
    return today - timedelta(days=days), today - timedelta(days=1)


Loaded = tuple[date, date, list[LogEntry], dict[int, Food]]


def load_intake(db: Session, user: User, days: int) -> Loaded:
    start, end = window(user, days)
    entries = entries_between(db, user, start, end)
    if not any(not e.is_supplement for e in entries):  # nothing logged before today: use today alone
        start = end = local_today(user)
        entries = entries_between(db, user, start, end)
    ids = {e.food_id for e in entries if e.is_supplement and e.food_id}
    foods = {f.id: f for f in db.scalars(select(Food).where(Food.id.in_(ids), visible(Food, user)))} if ids else {}
    return start, end, entries, foods


def check(db: Session, user: User, food: Food, servings_per_day: float | None, days: int,
          loaded: Loaded | None = None) -> dict:
    start, end, entries, foods = loaded or load_intake(db, user, days)
    # The product is compared with intake *without* it, so a supplement already being taken isn't counted twice.
    own = [e for e in entries if e.food_id == food.id and e.is_supplement]
    intake = Intake(user, [e for e in entries if not (e.food_id == food.id and e.is_supplement)], foods)
    already = Intake(user, entries, {**foods, food.id: food}).typical_servings(food.id) if own else None
    dose = servings_per_day or already or 1.0

    try:
        result = food_nutrition(food, dose, "serving", form_factors=form_factors(db, user, food))
    except NutritionError as exc:
        raise ValueError(str(exc)) from exc

    target_info = compute_targets(user.profile, end)
    targets = target_info["targets"]
    others = list(intake.supplements.values())
    uncounted: dict[str, list[dict]] = {}
    extra = []
    for c in result.other_components:
        if c.get("nutrient_code") and c.get("amount") is not None:
            uncounted.setdefault(c["nutrient_code"], []).append(
                {"name": c["name"], "amount": round(c["amount"], 3), "unit": c.get("unit"),
                 "resolvable": c.get("reason") == "form"})
        elif c.get("amount") is not None or c.get("name"):
            extra.append(c)

    rows = []
    for code in sorted({k for k, v in result.nutrients.items() if v > 0} | set(uncounted)):
        rows.append(_row(code, result.nutrients.get(code, 0.0), intake, others, targets.get(code), uncounted.get(code, [])))
    rows.sort(key=lambda r: (ORDER.index(r["status"]), r["name"]))

    other_ingredients = []
    for c in extra:
        key = _norm(c["name"])
        also = [{"label": s["label"], "amount": round(comp["amount"], 3), "unit": comp["unit"]}
                for s in others for (k, _), comp in s["components"].items() if k == key]
        other_ingredients.append({"name": c["name"], "amount": None if c.get("amount") is None else round(c["amount"], 3),
                                  "unit": c.get("unit"), "also_in": also})

    energy_target = (targets.get("energy_kcal") or {}).get("target")
    avg_energy = intake.food_energy / len(intake.days) if intake.days else 0.0
    confidence, reasons = "normal", []
    if len(intake.days) < MIN_LOGGED_DAYS:
        confidence = "low"
        reasons.append(f"Only {len(intake.days)} logged day{'s' if len(intake.days) != 1 else ''} to compare with; "
                       f"log at least {MIN_LOGGED_DAYS} for a steadier picture.")
    if energy_target and intake.days and avg_energy < LOW_ENERGY_SHARE * energy_target:
        confidence = "low"
        reasons.append(f"Logged food averages {avg_energy:,.0f} kcal a day against an estimated need of "
                       f"{energy_target:,.0f}, so some meals were probably not logged and food intake looks lower "
                       "than it is.")

    caveats = list(CAVEATS)
    life_stage = getattr(user.profile, "life_stage", "none") if user.profile else "none"
    if life_stage in ("pregnant", "lactating"):
        caveats.insert(0, f"While {life_stage}, some supplements (such as folic acid, iron or iodine) are often "
                          "recommended whatever your diet. Follow your clinician's advice over this check.")

    return {
        "product": {
            "food_id": food.id, "name": food.name, "brand": food.brand, "kind": food.kind, "trust_level": food.trust_level,
            "source": food.source, "citation": food.citation, "source_url": food.source_url,
            "servings_per_day": dose, "serving_label": _serving_label(food), "result_trust_level": result.trust_level,
            "notes": result.notes,
        },
        "window": {"start": start.isoformat(), "end": end.isoformat(), "logged_days": len(intake.days),
                   "avg_energy_kcal": round(avg_energy), "energy_target_kcal": energy_target},
        "already_taking": {"days_taken": len({local_date(user, e.consumed_at) for e in own}), "servings_per_day": already}
        if own else None,
        "verdict": _verdict(rows, other_ingredients, targets, confidence, reasons),
        "nutrients": rows,
        "other_ingredients": other_ingredients,
        "other_supplements": [{"food_id": s["food_id"], "label": s["label"], "days_taken": len(s["days"])}
                              for s in sorted(others, key=lambda s: s["label"].lower())],
        "warnings": target_info["warnings"],
        "caveats": caveats,
    }


def _serving_label(food: Food) -> str:
    if food.basis != "100g" and food.serving_quantity and food.serving_unit:
        return f"{food.serving_quantity:g} {food.serving_unit}"
    if food.serving_size_g:
        return f"{food.serving_size_g:g} g"
    return "1 serving"


def _row(code: str, product: float, intake: Intake, others: list[dict], t: dict | None, uncounted: list[dict]) -> dict:
    nd = BY_CODE.get(code)
    food = intake.food.get(code, 0.0)
    other = sum(s["nutrients"].get(code, 0.0) for s in others)
    t = t or {}
    ref = t.get("min") if t.get("min") is not None else t.get("target")
    limit = t.get("max") if t.get("max_is_limit", True) else None
    supplemental = t.get("ul_scope") == "supplemental"
    limit_without = other if supplemental else food + other
    limit_with = limit_without + product
    coverage = intake.coverage(code)

    if product <= 0 and uncounted:
        status = "partial"
    elif limit is not None and limit_with > limit:
        status = "over_limit"
    elif code in NOT_JUDGED:
        status = "info"
    elif ref is None:
        status = "no_reference"
    elif product < MINOR_SHARE * ref:
        status = "minor"
    elif food >= ref:
        status = "covered_by_food"
    elif food + other >= ref:
        status = "covered_by_supplements"
    elif food + other + product >= ref:
        status = "closes_gap"
    else:
        status = "narrows_gap"

    notes = []
    if status == "over_limit" and limit_without > limit:
        notes.append("Already over the upper limit without this product.")
    if supplemental and limit is not None:
        notes.append("The upper limit counts supplements only, not food.")
    if uncounted:
        notes.append("Part of the label amount can't be counted until its form is chosen.")
    uncertain = coverage is not None and coverage < LOW_COVERAGE and status in GAP
    if uncertain:
        notes.append(f"Only {coverage:.0%} of the food you logged (by calories) has a value for this nutrient, "
                     "so your food intake is probably higher than shown.")
    return {
        "code": code, "name": nd.name if nd else code, "unit": nd.unit if nd else "",
        "product": round(product, 3), "food": round(food, 3), "other_supplements": round(other, 3),
        "total_without": round(food + other, 3), "total_with": round(food + other + product, 3),
        "reference": ref, "reference_kind": t.get("kind"), "upper_limit": limit,
        "ul_scope": t.get("ul_scope") if limit is not None else None,
        "limit_amount_with": round(limit_with, 3) if limit is not None else None,
        "product_share_of_reference": round(product / ref, 3) if ref else None,
        "food_data_coverage": None if coverage is None else round(coverage, 2),
        "also_in": [s["label"] for s in others if s["nutrients"].get(code, 0) > 0],
        "uncounted": uncounted, "status": status, "uncertain": uncertain, "notes": notes,
    }


def _names(rows: list[dict]) -> str:
    names = [r["name"] for r in rows]
    return names[0] if len(names) == 1 else ", ".join(names[:-1]) + " and " + names[-1]


def _verdict(rows: list[dict], other_ingredients: list[dict], targets: dict, confidence: str, reasons: list[str]) -> dict:
    over = [r for r in rows if r["status"] == "over_limit"]
    gaps = [r for r in rows if r["status"] in GAP]
    covered = [r for r in rows if r["status"] in COVERED]
    unjudged = [r for r in rows if r["status"] == "no_reference"]
    details = []
    if not any(t.get("target") is not None or t.get("min") is not None for t in targets.values()):
        code, headline = "unknown", "Can't judge need without reference intakes for you."
        details.append("Add your sex and birth date in your profile (adults 19+), or set your own targets.")
    elif over:
        code, headline = "caution", f"Would take you over the upper limit for {_names(over)}."
    elif gaps and not covered:
        code, headline = "useful", f"Fills gaps in {_names(gaps)}."
    elif gaps:
        code, headline = "partly_useful", (f"Fills gaps in {_names(gaps)}; the other {len(covered)} "
                                           f"nutrient{'s are' if len(covered) != 1 else ' is'} already covered.")
    elif covered:
        code, headline = "not_needed", "Your food and other supplements already provide what this adds."
    else:
        code, headline = "unclear", "Nothing in this product has a reference intake in a meaningful amount."
    if over and gaps:
        details.append(f"It would also fill gaps in {_names(gaps)}; a lower dose or another product may do that without "
                       "going over the limit.")
    if any(r["uncertain"] for r in gaps):
        details.append("Some gaps may be smaller than shown: many food records don't report every nutrient.")
    if unjudged or other_ingredients:
        details.append(f"{len(unjudged) + len(other_ingredients)} ingredient"
                       f"{'s have' if len(unjudged) + len(other_ingredients) != 1 else ' has'} no reference intake, so "
                       "their need can't be judged from your intake. The adviser can summarise the evidence.")
    return {"code": code, "headline": headline, "details": details, "confidence": confidence,
            "confidence_reasons": reasons,
            "counts": {"over_limit": len(over), "gaps": len(gaps), "covered": len(covered),
                       "no_reference": len(unjudged) + len(other_ingredients)}}


def stack(db: Session, user: User, days: int) -> dict:
    """Every supplement taken in the window, each checked against everything else."""
    loaded = load_intake(db, user, days)
    start, end, entries, foods = loaded
    intake = Intake(user, entries, foods)
    items = []
    for s in sorted(intake.supplements.values(), key=lambda s: s["label"].lower()):
        food = foods.get(s["food_id"]) if s["food_id"] else None
        item = {"food_id": s["food_id"], "label": s["label"], "days_taken": len(s["days"]),
                "servings_per_day": round(s["servings"] / len(s["days"]), 2) if s["days"] else None}
        if food is None:
            item["verdict"] = None
            item["error"] = "This entry's product was deleted, so it can't be checked."
        else:
            try:
                result = check(db, user, food, item["servings_per_day"], days, loaded)
                item["verdict"] = result["verdict"]
            except ValueError as exc:
                item["verdict"], item["error"] = None, str(exc)
        items.append(item)
    return {"window": {"start": start.isoformat(), "end": end.isoformat(), "logged_days": len(intake.days)}, "items": items}
