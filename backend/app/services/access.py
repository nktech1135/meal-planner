from fastapi import HTTPException, status
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.models import CookingYield, Food, Recipe, User


def visible(model, user: User):
    """Shared rows (owner NULL) plus the user's own."""
    return or_(model.owner_id.is_(None), model.owner_id == user.id)


def get_food(db: Session, user: User, food_id: int) -> Food:
    food = db.scalar(select(Food).where(Food.id == food_id, visible(Food, user)))
    if food is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Food not found")
    return food


def get_yield(db: Session, user: User, yield_id: int) -> CookingYield:
    y = db.scalar(select(CookingYield).where(CookingYield.id == yield_id, visible(CookingYield, user)))
    if y is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Cooking yield not found")
    return y


def get_recipe(db: Session, user: User, recipe_id: int) -> Recipe:
    recipe = db.get(Recipe, recipe_id)
    if recipe is None or recipe.owner_id != user.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Recipe not found")
    return recipe


def recipe_yields(db: Session, user: User, recipe: Recipe) -> dict[int, CookingYield]:
    ids = {i.yield_id for i in recipe.ingredients if i.yield_id}
    if not ids:
        return {}
    rows = db.scalars(select(CookingYield).where(CookingYield.id.in_(ids), visible(CookingYield, user)))
    return {y.id: y for y in rows}
