from datetime import UTC, date, datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import LogEntry, User
from app.routers.conversions import calculate_nutrition
from app.schemas import LogIn, LogOut
from app.security import current_user
from app.services.access import get_food, get_recipe
from app.services.summary import day_summary, local_today, range_totals

router = APIRouter(prefix="/api", tags=["log"])


@router.post("/log", response_model=LogOut, status_code=201)
def add_entry(body: LogIn, user: User = Depends(current_user), db: Session = Depends(get_db)):
    if bool(body.food_id) == bool(body.recipe_id):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "Log exactly one of food_id or recipe_id")
    result = calculate_nutrition(db, user, body)
    if body.food_id:
        food = get_food(db, user, body.food_id)
        label = food.name + (f" ({food.brand})" if food.brand else "")
        is_supplement = food.kind == "supplement"
    else:
        label, is_supplement = get_recipe(db, user, body.recipe_id).name, False
    consumed_at = body.consumed_at or datetime.now(UTC)
    if consumed_at.tzinfo is None:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "consumed_at must include a timezone offset")
    entry = LogEntry(
        user_id=user.id, consumed_at=consumed_at, meal=body.meal, food_id=body.food_id, recipe_id=body.recipe_id,
        label=label, quantity=body.quantity, unit=body.unit, weighed_state=body.weighed_state, yield_id=body.yield_id,
        grams=result.grams, is_supplement=is_supplement, nutrients=result.nutrients,
        other_components=result.other_components, trust_level=result.trust_level, calc_notes=result.notes,
        note=body.note,
    )
    db.add(entry)
    db.commit()
    return entry


@router.delete("/log/{entry_id}", status_code=204)
def delete_entry(entry_id: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    entry = db.get(LogEntry, entry_id)
    if entry is None or entry.user_id != user.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Entry not found")
    db.delete(entry)
    db.commit()


@router.get("/summary/day")
def summary_day(day: date | None = None, user: User = Depends(current_user), db: Session = Depends(get_db)):
    summary = day_summary(db, user, day or local_today(user))
    summary["entries"] = [LogOut.model_validate(e) for e in summary["entries"]]
    return summary


@router.get("/summary/range")
def summary_range(
    start: date | None = None,
    end: date | None = None,
    days: int = Query(7, ge=1, le=366),
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
):
    end = end or local_today(user)
    start = start or end - timedelta(days=days - 1)
    if start > end or (end - start).days > 366:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "Invalid range")
    return range_totals(db, user, start, end)
