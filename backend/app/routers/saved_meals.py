from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import SavedMeal, SavedMealItem, User
from app.routers.conversions import calculate_nutrition
from app.routers.log import create_entry, item_label
from app.schemas import LogIn, LogOut, SavedMealFromLog, SavedMealIn, SavedMealLogIn, SavedMealOut
from app.security import current_user, signed_in_user
from app.services.sharing import acting_user
from app.services.summary import entries_between

router = APIRouter(prefix="/api/saved-meals", tags=["saved meals"])


def _own(db: Session, user: User, meal_id: int) -> SavedMeal:
    meal = db.get(SavedMeal, meal_id)
    if meal is None or meal.owner_id != user.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Saved meal not found")
    return meal


def _items(db: Session, user: User, body: SavedMealIn) -> list[SavedMealItem]:
    items = []
    for pos, it in enumerate(body.items):
        if bool(it.food_id) == bool(it.recipe_id):
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "Each item needs exactly one of food_id or recipe_id")
        calculate_nutrition(db, user, it)  # validates access, units and cooking yields up front
        label, _ = item_label(db, user, it.food_id, it.recipe_id)
        items.append(SavedMealItem(position=pos, label=label, **it.model_dump()))
    return items


@router.get("", response_model=list[SavedMealOut])
def list_meals(user: User = Depends(acting_user), db: Session = Depends(get_db)):
    return list(db.scalars(select(SavedMeal).where(SavedMeal.owner_id == user.id).order_by(SavedMeal.name)))


@router.post("", response_model=SavedMealOut, status_code=201)
def create_meal(body: SavedMealIn, user: User = Depends(current_user), db: Session = Depends(get_db)):
    meal = SavedMeal(owner_id=user.id, name=body.name, default_meal=body.default_meal, items=_items(db, user, body))
    db.add(meal)
    db.commit()
    return meal


@router.post("/from-log", response_model=SavedMealOut, status_code=201)
def create_from_log(body: SavedMealFromLog, user: User = Depends(current_user), db: Session = Depends(get_db)):
    entries = [e for e in entries_between(db, user, body.date, body.date)
               if e.meal == body.meal and (e.food_id or e.recipe_id)]
    if not entries:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Nothing logged for that meal")
    items = [{"food_id": e.food_id, "recipe_id": e.recipe_id, "quantity": e.quantity, "unit": e.unit,
              "weighed_state": e.weighed_state, "yield_id": e.yield_id} for e in entries]
    return create_meal(SavedMealIn(name=body.name, default_meal=body.meal, items=items), user, db)


@router.put("/{meal_id}", response_model=SavedMealOut)
def update_meal(meal_id: int, body: SavedMealIn, user: User = Depends(current_user), db: Session = Depends(get_db)):
    meal = _own(db, user, meal_id)
    meal.name, meal.default_meal = body.name, body.default_meal
    meal.items = _items(db, user, body)
    db.commit()
    return meal


@router.delete("/{meal_id}", status_code=204)
def delete_meal(meal_id: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    db.delete(_own(db, user, meal_id))
    db.commit()


@router.post("/{meal_id}/log", response_model=list[LogOut], status_code=201)
def log_meal(meal_id: int, body: SavedMealLogIn, user: User = Depends(current_user), me: User = Depends(signed_in_user),
             db: Session = Depends(get_db)):
    meal = _own(db, user, meal_id)
    when = body.consumed_at or datetime.now(UTC)
    entries = [create_entry(db, user, LogIn(
        consumed_at=when, meal=body.meal or meal.default_meal, food_id=it.food_id, recipe_id=it.recipe_id,
        quantity=it.quantity, unit=it.unit, weighed_state=it.weighed_state, yield_id=it.yield_id,
    ), me) for it in meal.items]
    db.commit()
    return entries
