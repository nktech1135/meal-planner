"""Read-only tools the advisor can call. Every tool is scoped to the signed-in user."""

import json
from datetime import date, timedelta

from fastapi import HTTPException
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.models import BodyMeasurement, Food, PlanProposal, Recipe, User
from app.nutrients import BY_CODE
from app.routers.plan import plan_days, validate_item
from app.schemas import PlanItemIn
from app.services import supplement_check
from app.services.access import get_food, recipe_yields, visible
from app.services.nutrition import NutritionError, recipe_nutrition
from app.services.summary import day_summary, entries_between, local_date, local_today, range_totals
from app.services.targets import compute_targets
from app.services.trends import trends

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
        "name": "check_supplement",
        "description": "Whether a supplement product is needed. Compares its daily dose, nutrient by nutrient, with the "
                       "user's average intake from food and from their other supplements over recent logged days, "
                       "against their reference intakes and upper limits (supplement-only limits use supplement intake). "
                       "Also lists ingredients with no reference intake (e.g. botanicals) and which of the user's other "
                       "supplements contain them. Get food_id from search_foods. servings_per_day 0 means the user's "
                       "usual dose if they already take it, otherwise 1. days is the look-back (3-90, usually 14).",
        "input_schema": _obj({"food_id": {"type": "integer"}, "servings_per_day": {"type": "number"},
                              "days": {"type": "integer"}}),
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
    {
        "name": "get_trends",
        "description": "Averages over the last N days (logged days only) against every target, how many logged "
                       "days met each target, the weight trend, and an estimate of maintenance energy from intake "
                       "and weight change when there is enough data. Prefer this over single days for vitamins and minerals.",
        "input_schema": _obj({"days": {"type": "integer", "description": "7 to 90"}}),
    },
    {
        "name": "get_body_measurements",
        "description": "Weight, body fat and waist measurements over a date range (max 365 days).",
        "input_schema": _obj({"start_date": _DATE, "end_date": _DATE}),
    },
    {
        "name": "get_meal_plan",
        "description": "Planned items per day with projected nutrient totals (max 31 days).",
        "input_schema": _obj({"start_date": _DATE, "end_date": _DATE}),
    },
    {
        "name": "propose_plan_items",
        "description": "Suggest items for the user's meal plan. Nothing is added until the user reviews and accepts "
                       "the proposal in the app, so explain what you proposed. Use food_id or recipe_id values "
                       "from search_foods / list_recipes (exactly one per item). unit is 'g' (grams of the food as "
                       "described), 'serving', or 'unit' for per-serving supplements.",
        "input_schema": _obj({
            "rationale": {"type": "string", "description": "One or two sentences on why"},
            "items": {"type": "array", "items": _obj({
                "date": _DATE,
                "meal": {"type": "string", "enum": ["breakfast", "lunch", "dinner", "snack", "supplement"]},
                "food_id": {"anyOf": [{"type": "integer"}, {"type": "null"}]},
                "recipe_id": {"anyOf": [{"type": "integer"}, {"type": "null"}]},
                "quantity": {"type": "number"},
                "unit": {"type": "string", "enum": ["g", "serving", "unit"]},
            })},
        }),
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


def run_tool(db: Session, user: User, name: str, args: dict, conversation_id: int | None = None) -> str:
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
        hidden = (user.profile.hidden_sources if user.profile else None) or []
        if hidden:
            stmt = stmt.where(Food.source.not_in(hidden))
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
    elif name == "get_trends":
        days = max(7, min(90, int(args["days"])))
        end = local_today(user)
        t = trends(db, user, end - timedelta(days=days - 1), end)
        result = {
            "start": t["start"], "end": t["end"], "logged_days": t["logged_days"], "of_days": t["days"],
            "daily_averages_vs_targets": [{k: r.get(k) for k in ("code", "amount", "limit_amount", "status", "min",
                                                                  "target", "max", "kind", "ul_scope", "days_ok")}
                                          for r in t["evaluation"]],
            "weight_trend": (t["weight"][0], t["weight"][-1]) if t["weight"] else None,
            "energy_estimate": t["energy_estimate"], "warnings": t["warnings"],
        }
    elif name == "get_body_measurements":
        start, end = _span(args, 365)
        result = [{"date": m.date.isoformat(), "weight_kg": m.weight_kg, "body_fat_pct": m.body_fat_pct,
                   "waist_cm": m.waist_cm, "note": m.note}
                  for m in db.scalars(select(BodyMeasurement).where(
                      BodyMeasurement.user_id == user.id, BodyMeasurement.date >= start, BodyMeasurement.date <= end)
                      .order_by(BodyMeasurement.date))]
    elif name == "get_meal_plan":
        start, end = _span(args, 31)
        result = [{"date": d["date"], "items": [{k: i[k] for k in ("meal", "label", "quantity", "unit", "food_id",
                                                                    "recipe_id", "logged_entry_id", "error")}
                                                 for i in d["items"]],
                   "totals": _named(d["totals"])} for d in plan_days(db, user, start, end) if d["items"]]
    elif name == "check_supplement":
        try:
            food = get_food(db, user, int(args["food_id"]))
            result = supplement_check.check(db, user, food, args.get("servings_per_day") or None,
                                            max(3, min(90, int(args.get("days") or 14))))
        except HTTPException as exc:
            result = {"error": exc.detail}
        except ValueError as exc:
            result = {"error": str(exc)}
    elif name == "propose_plan_items":
        result = _propose(db, user, args, conversation_id)
    else:
        raise ValueError(f"Unknown tool {name}")

    text = json.dumps(result, default=str)
    if len(text) > MAX_RESULT_CHARS:
        text = text[:MAX_RESULT_CHARS] + ' ... [truncated: narrow the date range or query]'
    return text


def _propose(db: Session, user: User, args: dict, conversation_id: int | None) -> dict:
    """Validate each suggested item and store the valid ones as a pending proposal."""
    accepted, problems = [], []
    for i, raw in enumerate(args.get("items") or []):
        try:
            item = PlanItemIn(**{k: v for k, v in raw.items() if v is not None})
            label = validate_item(db, user, item)
        except HTTPException as exc:
            problems.append({"index": i, "error": str(exc.detail)})
            continue
        except ValueError as exc:
            problems.append({"index": i, "error": str(exc)})
            continue
        accepted.append({**item.model_dump(mode="json"), "label": label})
    if not accepted:
        return {"proposal_id": None, "problems": problems, "note": "Nothing valid to propose."}
    proposal = PlanProposal(user_id=user.id, conversation_id=conversation_id, rationale=args.get("rationale", ""),
                            items=accepted)
    db.add(proposal)
    db.flush()
    return {"proposal_id": proposal.id, "items_proposed": len(accepted), "problems": problems,
            "note": "Shown to the user for review; not yet in their plan."}
