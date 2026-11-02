from datetime import UTC, date, datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import Food, LogEntry, User
from app.routers.conversions import calculate_nutrition
from app.schemas import CopyIn, ExerciseOut, LogIn, LogOut, LogUpdate, SuggestionOut
from app.security import current_user, signed_in_user
from app.services.access import get_food, get_recipe
from app.services.summary import day_summary, entries_between, local_today, range_totals, user_tz

router = APIRouter(prefix="/api", tags=["log"])


def item_label(db: Session, user: User, food_id: int | None, recipe_id: int | None) -> tuple[str, bool]:
    if food_id:
        food = get_food(db, user, food_id)
        return food.name + (f" ({food.brand})" if food.brand else ""), food.kind == "supplement"
    return get_recipe(db, user, recipe_id).name, False


def _utc_time(when: datetime) -> datetime:
    """Stored in UTC: SQLite keeps the clock time and drops the offset, and readers take it as UTC."""
    if when.tzinfo is None:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "consumed_at must include a timezone offset")
    return when.astimezone(UTC)


def create_entry(db: Session, user: User, body: LogIn, actor: User | None = None) -> LogEntry:
    """Calculate and add (not commit) a log entry to ``user``'s log, made by ``actor`` (default: them)."""
    if bool(body.food_id) == bool(body.recipe_id):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "Log exactly one of food_id or recipe_id")
    consumed_at = _utc_time(body.consumed_at or datetime.now(UTC))
    result = calculate_nutrition(db, user, body)
    label, is_supplement = item_label(db, user, body.food_id, body.recipe_id)
    entry = LogEntry(
        user_id=user.id, consumed_at=consumed_at, meal=body.meal, food_id=body.food_id, recipe_id=body.recipe_id,
        label=label, quantity=body.quantity, unit=body.unit, weighed_state=body.weighed_state, yield_id=body.yield_id,
        grams=result.grams, is_supplement=is_supplement, nutrients=result.nutrients,
        other_components=result.other_components, trust_level=result.trust_level, calc_notes=result.notes,
        note=body.note, created_by_id=(actor or user).id,
    )
    db.add(entry)
    return entry


def _own_entry(db: Session, user: User, entry_id: int) -> LogEntry:
    entry = db.get(LogEntry, entry_id)
    if entry is None or entry.user_id != user.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Entry not found")
    return entry


def _as_input(entry: LogEntry, **changes) -> LogIn:
    fields = {k: getattr(entry, k) for k in ("consumed_at", "meal", "food_id", "recipe_id", "quantity", "unit",
                                             "weighed_state", "yield_id", "note")}
    if fields["consumed_at"].tzinfo is None:  # SQLite returns naive UTC
        fields["consumed_at"] = fields["consumed_at"].replace(tzinfo=UTC)
    return LogIn(**{**fields, **changes})


@router.post("/log", response_model=LogOut, status_code=201)
def add_entry(body: LogIn, user: User = Depends(current_user), me: User = Depends(signed_in_user),
              db: Session = Depends(get_db)):
    entry = create_entry(db, user, body, me)
    db.commit()
    return entry


@router.patch("/log/{entry_id}", response_model=LogOut)
def update_entry(entry_id: int, body: LogUpdate, user: User = Depends(current_user), db: Session = Depends(get_db)):
    """Edit an entry. Changing the amount recalculates its nutrients from the current food or recipe data;
    changing only the time, meal or note keeps the nutrients worked out when it was logged."""
    entry = _own_entry(db, user, entry_id)
    changes = body.model_dump(exclude_unset=True)
    if "consumed_at" in changes:
        changes["consumed_at"] = _utc_time(changes["consumed_at"])
    amount_fields = {"quantity", "unit", "weighed_state", "yield_id"}
    if not amount_fields & changes.keys():
        for key, value in changes.items():
            setattr(entry, key, value)
        db.commit()
        return entry
    if entry.food_id is None and entry.recipe_id is None:
        raise HTTPException(status.HTTP_409_CONFLICT,
                            "The food for this entry was deleted; only time, meal and note can change")
    recalculate(db, user, entry, **changes)
    db.commit()
    return entry


def recalculate(db: Session, user: User, entry: LogEntry, **changes) -> None:
    """Recompute an entry's nutrients from current data, applying ``changes`` (not committed)."""
    replacement = create_entry(db, user, _as_input(entry, **changes))
    for key in ("consumed_at", "meal", "quantity", "unit", "weighed_state", "yield_id", "note", "label", "grams",
                "is_supplement", "nutrients", "other_components", "trust_level", "calc_notes"):
        setattr(entry, key, getattr(replacement, key))
    db.expunge(replacement)


@router.post("/log/copy", response_model=list[LogOut], status_code=201)
def copy_entries(body: CopyIn, user: User = Depends(current_user), me: User = Depends(signed_in_user),
                 db: Session = Depends(get_db)):
    """Copy a day's entries (or one meal's) to another day, keeping the time of day."""
    sources = [e for e in entries_between(db, user, body.from_date, body.from_date)
               if body.meal is None or e.meal == body.meal]
    if not sources:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Nothing logged to copy")
    tz = user_tz(user)
    created = []
    for e in sources:
        if e.food_id is None and e.recipe_id is None:
            continue  # its food was deleted; nothing to recalculate from
        when = e.consumed_at if e.consumed_at.tzinfo else e.consumed_at.replace(tzinfo=UTC)
        local = when.astimezone(tz)
        moved = datetime.combine(body.to_date, local.timetz())
        created.append(create_entry(db, user, _as_input(e, consumed_at=moved, meal=body.to_meal or e.meal), me))
    db.commit()
    return created


@router.get("/log/suggestions", response_model=list[SuggestionOut])
def suggestions(
    meal: str | None = None,
    q: str = "",
    limit: int = Query(12, le=50),
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
):
    """Things this user logs, most relevant first: same meal, then frequency, then recency (last 90 days)."""
    since = datetime.now(UTC) - timedelta(days=90)
    rows = db.scalars(select(LogEntry).where(LogEntry.user_id == user.id, LogEntry.consumed_at >= since)
                      .order_by(LogEntry.consumed_at.desc()))
    groups: dict[tuple, dict] = {}
    for e in rows:
        if e.food_id is None and e.recipe_id is None:
            continue
        key = (e.food_id, e.recipe_id)
        g = groups.get(key)
        if g is None:  # newest first, so the first entry seen carries the "last used" amount
            groups[key] = g = {"entry": e, "times": 0, "meals": {}}
        g["times"] += 1
        g["meals"][e.meal] = g["meals"].get(e.meal, 0) + 1
    terms = q.lower().split()
    out = []
    for (food_id, recipe_id), g in groups.items():
        e = g["entry"]
        if terms and not all(t in e.label.lower() for t in terms):
            continue
        if food_id:
            food = db.get(Food, food_id)
            kind, trust = (food.kind, food.trust_level) if food else ("food", e.trust_level)
        else:
            kind, trust = "recipe", e.trust_level
        out.append((g["meals"].get(meal, 0) if meal else 0, g["times"], e.consumed_at, SuggestionOut(
            food_id=food_id, recipe_id=recipe_id, label=e.label, kind=kind, trust_level=trust, quantity=e.quantity,
            unit=e.unit, weighed_state=e.weighed_state, yield_id=e.yield_id, meal=e.meal, times=g["times"],
            last_used=e.consumed_at, energy_kcal=e.nutrients.get("energy_kcal"))))
    out.sort(key=lambda t: (t[0], t[1], t[2]), reverse=True)
    return [s for *_, s in out[:limit]]


@router.delete("/log/{entry_id}", status_code=204)
def delete_entry(entry_id: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    db.delete(_own_entry(db, user, entry_id))
    db.commit()


@router.get("/summary/day")
def summary_day(day: date | None = None, user: User = Depends(current_user), db: Session = Depends(get_db)):
    summary = day_summary(db, user, day or local_today(user))
    summary["entries"] = [LogOut.model_validate(e) for e in summary["entries"]]
    summary["exercises"] = [ExerciseOut.model_validate(x) for x in summary["exercises"]]
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
