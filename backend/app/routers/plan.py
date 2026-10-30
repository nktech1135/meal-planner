"""Meal planning: plan items per day, projected nutrition, logging plans, shopping lists."""

from datetime import UTC, date, datetime, time, timedelta

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import Food, LogEntry, PlanItem, SavedMeal, ShoppingCheck, User
from app.routers.conversions import calculate_nutrition
from app.routers.log import create_entry, item_label
from app.schemas import (
    LogIn,
    LogOut,
    PlanCopyIn,
    PlanFromSavedIn,
    PlanItemIn,
    PlanItemUpdate,
    PlanLogIn,
    ShoppingCheckIn,
)
from app.security import current_user
from app.services.access import get_food, get_recipe, get_yield, recipe_yields
from app.services.nutrition import NutritionError, add_into, food_nutrition, rounded
from app.services.summary import evaluate, user_tz
from app.services.targets import compute_targets

router = APIRouter(prefix="/api/plan", tags=["plan"])

MEAL_TIMES = {"breakfast": time(8, 0), "lunch": time(12, 30), "snack": time(15, 30), "dinner": time(18, 30),
              "supplement": time(8, 0)}
MAX_DAYS = 62


def _range(start: date, end: date) -> None:
    if end < start or (end - start).days >= MAX_DAYS:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, f"Choose a range of 1–{MAX_DAYS} days")


def _own(db: Session, user: User, item_id: int) -> PlanItem:
    item = db.get(PlanItem, item_id)
    if item is None or item.user_id != user.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Plan item not found")
    return item


def _validate(db: Session, user: User, body) -> str:
    """Check access, units and yields the same way logging does; returns the item's label."""
    if bool(body.food_id) == bool(body.recipe_id):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "Plan exactly one of food_id or recipe_id")
    calculate_nutrition(db, user, body)
    return item_label(db, user, body.food_id, body.recipe_id)[0]


def item_out(db: Session, user: User, item: PlanItem) -> dict:
    out = {k: getattr(item, k) for k in ("id", "date", "meal", "position", "food_id", "recipe_id", "label", "quantity",
                                         "unit", "weighed_state", "yield_id", "note", "origin", "logged_entry_id")}
    try:
        result = calculate_nutrition(db, user, item)
        out.update(nutrients=result.nutrients, trust_level=result.trust_level, grams=result.grams, error=None)
    except HTTPException as exc:
        out.update(nutrients={}, trust_level=None, grams=None, error=exc.detail)
    return out


def plan_days(db: Session, user: User, start: date, end: date) -> list[dict]:
    items = list(db.scalars(select(PlanItem).where(PlanItem.user_id == user.id, PlanItem.date >= start,
                                                   PlanItem.date <= end)
                            .order_by(PlanItem.date, PlanItem.position, PlanItem.id)))
    targets = compute_targets(user.profile, start)["targets"]
    days = []
    for i in range((end - start).days + 1):
        d = start + timedelta(days=i)
        rows = [item_out(db, user, it) for it in items if it.date == d]
        totals: dict[str, float] = {}
        supplements: dict[str, float] = {}
        for row, it in zip(rows, [it for it in items if it.date == d], strict=True):
            add_into(totals, row["nutrients"])
            if it.food_id and (food := db.get(Food, it.food_id)) and food.kind == "supplement":
                add_into(supplements, row["nutrients"])
        days.append({"date": d.isoformat(), "items": rows, "totals": rounded(totals),
                     "evaluation": evaluate(totals, supplements, targets) if rows else []})
    return days


@router.get("")
def get_plan(start: date, end: date, user: User = Depends(current_user), db: Session = Depends(get_db)):
    _range(start, end)
    return plan_days(db, user, start, end)


@router.post("", status_code=201)
def add_item(body: PlanItemIn, user: User = Depends(current_user), db: Session = Depends(get_db)):
    return create_item(db, user, body, "manual")


def create_item(db: Session, user: User, body: PlanItemIn, origin: str) -> dict:
    label = _validate(db, user, body)
    last = db.scalar(select(PlanItem.position).where(PlanItem.user_id == user.id, PlanItem.date == body.date)
                     .order_by(PlanItem.position.desc()).limit(1))
    item = PlanItem(user_id=user.id, label=label, position=(last or 0) + 1, origin=origin, **body.model_dump())
    db.add(item)
    db.commit()
    return item_out(db, user, item)


@router.patch("/{item_id}")
def update_item(item_id: int, body: PlanItemUpdate, user: User = Depends(current_user), db: Session = Depends(get_db)):
    item = _own(db, user, item_id)
    changes = body.model_dump(exclude_unset=True)
    merged = PlanItemIn(**{**{k: getattr(item, k) for k in PlanItemIn.model_fields}, **changes})
    _validate(db, user, merged)
    for key, value in changes.items():
        setattr(item, key, value)
    db.commit()
    return item_out(db, user, item)


@router.delete("/{item_id}", status_code=204)
def delete_item(item_id: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    db.delete(_own(db, user, item_id))
    db.commit()


def _log_item(db: Session, user: User, item: PlanItem) -> LogEntry:
    tz = user_tz(user)
    now = datetime.now(UTC)
    when = datetime.combine(item.date, MEAL_TIMES.get(item.meal, time(12, 0)), tzinfo=tz)
    if item.date == now.astimezone(tz).date() and when > now:
        when = now  # logging today's plan early: record it now rather than in the future
    entry = create_entry(db, user, LogIn(consumed_at=when, meal=item.meal, food_id=item.food_id,
                                         recipe_id=item.recipe_id, quantity=item.quantity, unit=item.unit,
                                         weighed_state=item.weighed_state, yield_id=item.yield_id, note=item.note))
    db.flush()
    item.logged_entry_id = entry.id
    return entry


@router.post("/{item_id}/log", response_model=LogOut, status_code=201)
def log_item(item_id: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    item = _own(db, user, item_id)
    if item.logged_entry_id and db.get(LogEntry, item.logged_entry_id):
        raise HTTPException(status.HTTP_409_CONFLICT, "Already logged")
    entry = _log_item(db, user, item)
    db.commit()
    return entry


@router.post("/log-day", response_model=list[LogOut], status_code=201)
def log_day(body: PlanLogIn, user: User = Depends(current_user), db: Session = Depends(get_db)):
    """Log every not-yet-logged item for a day (or one meal of it)."""
    items = [it for it in db.scalars(select(PlanItem).where(PlanItem.user_id == user.id, PlanItem.date == body.date)
                                     .order_by(PlanItem.position))
             if (body.meal is None or it.meal == body.meal)
             and not (it.logged_entry_id and db.get(LogEntry, it.logged_entry_id))]
    entries = [_log_item(db, user, it) for it in items]
    db.commit()
    return entries


@router.post("/copy", status_code=201)
def copy_plan(body: PlanCopyIn, user: User = Depends(current_user), db: Session = Depends(get_db)):
    _range(body.from_start, body.from_end)
    shift = body.to_start - body.from_start
    sources = list(db.scalars(select(PlanItem).where(PlanItem.user_id == user.id, PlanItem.date >= body.from_start,
                                                     PlanItem.date <= body.from_end).order_by(PlanItem.date, PlanItem.position)))
    if not sources:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Nothing planned in that range")
    for it in sources:
        db.add(PlanItem(user_id=user.id, date=it.date + shift, meal=it.meal, position=it.position, food_id=it.food_id,
                        recipe_id=it.recipe_id, label=it.label, quantity=it.quantity, unit=it.unit,
                        weighed_state=it.weighed_state, yield_id=it.yield_id, note=it.note, origin="copy"))
    db.commit()
    return {"copied": len(sources)}


@router.post("/from-saved-meal", status_code=201)
def plan_saved_meal(body: PlanFromSavedIn, user: User = Depends(current_user), db: Session = Depends(get_db)):
    meal = db.get(SavedMeal, body.saved_meal_id)
    if meal is None or meal.owner_id != user.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Saved meal not found")
    out = []
    for it in meal.items:
        out.append(create_item(db, user, PlanItemIn(date=body.date, meal=body.meal or meal.default_meal,
                                                    food_id=it.food_id, recipe_id=it.recipe_id, quantity=it.quantity,
                                                    unit=it.unit, weighed_state=it.weighed_state, yield_id=it.yield_id),
                               "saved_meal"))
    return out


# --- Shopping list -----------------------------------------------------------------

def _food_need(db: Session, user: User, food: Food, quantity: float, unit: str, weighed_state: str,
               yield_id: int | None) -> tuple[str, float]:
    """(unit, amount) of a food to buy: grams for weighed foods (raw for cooked weights), servings otherwise."""
    if weighed_state == "cooked" and yield_id:
        y = get_yield(db, user, yield_id)
        cooked_g = quantity if unit == "g" else food_nutrition(food, quantity, unit).grams or 0
        return "g", cooked_g / y.yield_factor
    try:
        grams = food_nutrition(food, quantity, unit).grams
    except NutritionError:
        grams = None
    if grams:
        return "g", grams
    if food.basis == "serving":
        servings = quantity if unit == "serving" else quantity / (food.serving_quantity or 1)
        return f"servings ({food.serving_quantity or 1:g} {food.serving_unit or 'unit'})", servings
    return unit, quantity


@router.get("/shopping")
def shopping_list(start: date, end: date, include_logged: bool = False, user: User = Depends(current_user),
                  db: Session = Depends(get_db)):
    """Everything needed for the planned days, with recipes broken down into their ingredients."""
    _range(start, end)
    needs: dict[tuple[int, str], dict] = {}

    def need(food: Food, unit: str, amount: float, used_for: str) -> None:
        row = needs.setdefault((food.id, unit), {"food_id": food.id, "name": food.name, "brand": food.brand,
                                                 "category": food.category or ("Supplements" if food.kind == "supplement"
                                                                               else "Other"),
                                                 "unit": unit, "amount": 0.0, "used_for": set()})
        row["amount"] += amount
        row["used_for"].add(used_for)

    for it in db.scalars(select(PlanItem).where(PlanItem.user_id == user.id, PlanItem.date >= start,
                                                PlanItem.date <= end)):
        if it.logged_entry_id and not include_logged and db.get(LogEntry, it.logged_entry_id):
            continue
        try:
            if it.food_id:
                food = get_food(db, user, it.food_id)
                unit, amount = _food_need(db, user, food, it.quantity, it.unit, it.weighed_state, it.yield_id)
                need(food, unit, amount, it.label)
            else:
                recipe = get_recipe(db, user, it.recipe_id)
                if it.unit == "serving":
                    share = it.quantity / (recipe.servings or 1)
                elif recipe.cooked_weight_g:
                    share = it.quantity / recipe.cooked_weight_g
                else:
                    continue
                yields = recipe_yields(db, user, recipe)
                for ing in recipe.ingredients:
                    unit, amount = _food_need(db, user, ing.food, ing.grams, "g", ing.weighed_state, ing.yield_id)
                    if ing.yield_id not in yields:
                        unit, amount = "g", ing.grams
                    need(ing.food, unit, amount * share, recipe.name)
        except HTTPException:
            continue  # a food or recipe that was since deleted

    prefix = f"{start}:{end}:"
    checked = {c.key.removeprefix(prefix) for c in db.scalars(
        select(ShoppingCheck).where(ShoppingCheck.user_id == user.id, ShoppingCheck.key.startswith(prefix)))}
    items = []
    for row in needs.values():
        key = f"{row['food_id']}:{row['unit']}"[:80]
        items.append({**row, "key": key, "amount": round(row["amount"], 1), "used_for": sorted(row["used_for"]),
                      "checked": key in checked})
    items.sort(key=lambda r: (r["category"], r["name"]))
    return {"start": start.isoformat(), "end": end.isoformat(), "items": items}


@router.put("/shopping/check", status_code=204)
def check_item(body: ShoppingCheckIn, user: User = Depends(current_user), db: Session = Depends(get_db)):
    key = f"{body.start}:{body.end}:{body.key}"
    if body.checked:
        if db.get(ShoppingCheck, (user.id, key)) is None:
            db.add(ShoppingCheck(user_id=user.id, key=key))
    else:
        db.execute(delete(ShoppingCheck).where(ShoppingCheck.user_id == user.id, ShoppingCheck.key == key))
    db.commit()
