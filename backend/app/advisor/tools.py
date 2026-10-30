"""Read-only tools the advisor can call. Every tool is scoped to the signed-in user."""

import json
from datetime import date, timedelta

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.models import Food, Recipe, User
from app.nutrients import BY_CODE
from app.services.access import recipe_yields, visible
from app.services.nutrition import NutritionError, recipe_nutrition
from app.services.summary import day_summary, entries_between, local_date, local_today, range_totals
from app.services.targets import compute_targets

MAX_RESULT_CHARS = 30_000


def _obj(properties: dict) -> dict:
    return {"type": "object", "properties": properties, "required": list(properties), "additionalProperties": False}


_DATE = {"type": "string", "description": "ISO date YYYY-MM-DD in the user's timezone"}

TOOLS = [
    {
        "name": "get_profile_and_targets",
        "description": "The user's profile (sex, age inputs, body size, activity, goal, life stage, health notes) "
                       "and their daily nutrient targets with the source of each target.",
        "input_schema": _obj({}),
    },
    {
        "name": "get_day_summary",
        "description": "One day's logged entries, nutrient totals, supplement-only totals, comparison against each "
                       "target and upper limit, alerts, and how much energy came from each data-trust level.",
        "input_schema": _obj({"date": _DATE}),
    },
    {
        "name": "get_daily_totals",
        "description": "Per-day nutrient totals over a date range (max 92 days) for spotting trends. "
                       "Days with zero entries were probably not logged rather than fasted.",
        "input_schema": _obj({"start_date": _DATE, "end_date": _DATE}),
    },
    {
        "name": "get_log_entries",
        "description": "Individual log entries (what was eaten or taken, amount, meal, trust level, calculation notes) "
                       "over a date range (max 31 days).",
        "input_schema": _obj({"start_date": _DATE, "end_date": _DATE}),
    },
    {
        "name": "search_foods",
        "description": "Search foods and supplements in this app's database (the user's own entries and imported "
                       "records). Returns ids, trust level and macros on the food's basis.",
        "input_schema": _obj({
            "query": {"type": "string"},
            "kind": {"type": "string", "enum": ["food", "supplement", "any"]},
        }),
    },
    {
        "name": "get_food_details",
        "description": "Full nutrient profile, portions, source citation and trust level for one food id.",
        "input_schema": _obj({"food_id": {"type": "integer"}}),
    },
    {
        "name": "list_recipes",
        "description": "The user's recipes with per-serving nutrition.",
        "input_schema": _obj({}),
    },
]
for _t in TOOLS:
    _t["strict"] = True


def _named(values: dict[str, float]) -> dict[str, str]:
    out = {}
    for code, v in values.items():
        n = BY_CODE.get(code)
        out[n.name if n else code] = f"{v:.4g} {n.unit if n else ''}".strip()
    return out


def _date(value: str) -> date:
    return date.fromisoformat(value)


def _span(args: dict, max_days: int) -> tuple[date, date]:
    start, end = _date(args["start_date"]), _date(args["end_date"])
    if start > end:
        start, end = end, start
    if (end - start).days >= max_days:
        start = end - timedelta(days=max_days - 1)
    return start, end


def _entry(user: User, e) -> dict:
    return {
        "date": local_date(user, e.consumed_at).isoformat(), "meal": e.meal, "item": e.label,
        "amount": f"{e.quantity:g} {e.unit}" + (" (weighed cooked)" if e.weighed_state == "cooked" else ""),
        "supplement": e.is_supplement, "trust_level": e.trust_level,
        "energy_kcal": round(e.nutrients.get("energy_kcal", 0)), "protein_g": round(e.nutrients.get("protein_g", 0), 1),
        "notes": e.calc_notes,
    }


def run_tool(db: Session, user: User, name: str, args: dict) -> str:
    if name == "get_profile_and_targets":
        p = user.profile
        today = local_today(user)
        profile = {
            "sex": p.sex, "birth_date": p.birth_date.isoformat() if p.birth_date else None, "height_cm": p.height_cm,
            "weight_kg": p.weight_kg, "activity_level": p.activity_level, "goal": p.goal, "life_stage": p.life_stage,
            "timezone": p.timezone, "health_notes": p.health_notes,
        } if p else {}
        result = {"profile": profile, "today": today.isoformat(), **compute_targets(p, today)}
    elif name == "get_day_summary":
        s = day_summary(db, user, _date(args["date"]))
        result = {
            "date": s["date"], "entries": [_entry(user, e) for e in s["entries"]],
            "totals": _named(s["totals"]), "supplement_totals": _named(s["supplement_totals"]),
            "other_supplement_components": s["other_components"],
            "vs_targets": [{k: r.get(k) for k in ("code", "amount", "limit_amount", "status", "min", "target", "max",
                                                  "kind", "ul_scope", "note")} for r in s["evaluation"]],
            "alerts": s["alerts"], "warnings": s["warnings"], "energy_kcal_by_trust_level": s["energy_by_trust"],
        }
    elif name == "get_daily_totals":
        start, end = _span(args, 92)
        result = [{"date": d["date"], "entries": d["entries"], "totals": {k: round(v, 2) for k, v in d["totals"].items()}}
                  for d in range_totals(db, user, start, end)]
    elif name == "get_log_entries":
        start, end = _span(args, 31)
        result = [_entry(user, e) for e in entries_between(db, user, start, end)]
    elif name == "search_foods":
        stmt = select(Food).where(visible(Food, user))
        for term in args["query"].split():
            stmt = stmt.where(or_(Food.name.ilike(f"%{term}%"), Food.brand.ilike(f"%{term}%")))
        if args.get("kind") in ("food", "supplement"):
            stmt = stmt.where(Food.kind == args["kind"])
        result = [{
            "food_id": f.id, "name": f.name, "brand": f.brand, "kind": f.kind, "state": f.state,
            "basis": "per 100 g" if f.basis == "100g" else f"per serving ({f.serving_quantity:g} {f.serving_unit})",
            "trust_level": f.trust_level, "source": f.source,
            "macros": _named({k: v for k, v in f.nutrient_map().items()
                              if k in ("energy_kcal", "protein_g", "fat_g", "carbs_g", "fiber_g")}),
        } for f in db.scalars(stmt.order_by(Food.name).limit(25))]
    elif name == "get_food_details":
        f = db.scalar(select(Food).where(Food.id == args["food_id"], visible(Food, user)))
        if f is None:
            raise ValueError("No such food")
        result = {
            "food_id": f.id, "name": f.name, "brand": f.brand, "kind": f.kind, "state": f.state,
            "basis": f.basis, "serving": f"{f.serving_quantity or ''} {f.serving_unit or ''}".strip() or None,
            "trust_level": f.trust_level, "source": f.source, "data_type": f.source_data_type,
            "citation": f.citation, "nutrients": _named(f.nutrient_map()),
            "other_components": f.other_components, "portions": [{p.label: p.gram_weight} for p in f.portions],
        }
    elif name == "list_recipes":
        result = []
        for r in db.scalars(select(Recipe).where(Recipe.owner_id == user.id).order_by(Recipe.name)):
            try:
                info = recipe_nutrition(r, recipe_yields(db, user, r))
                result.append({"recipe_id": r.id, "name": r.name, "servings": r.servings,
                               "per_serving": _named(info["per_serving"]), "trust_level": info["trust_level"]})
            except NutritionError as exc:
                result.append({"recipe_id": r.id, "name": r.name, "error": str(exc)})
    else:
        raise ValueError(f"Unknown tool {name}")

    text = json.dumps(result, default=str)
    if len(text) > MAX_RESULT_CHARS:
        text = text[:MAX_RESULT_CHARS] + ' ... [truncated: narrow the date range or query]'
    return text
