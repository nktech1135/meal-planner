from fastapi import HTTPException, status
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.models import (
    CookingYield,
    Food,
    FormChoice,
    PlanItem,
    Recipe,
    RecipeIngredient,
    SavedMeal,
    SavedMealItem,
    User,
)
from app.services.forms import option


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


def _count(db: Session, column, value) -> int:
    return db.scalar(select(func.count()).where(column == value)) or 0


def yield_uses(db: Session, yield_id: int) -> str | None:
    """What still converts cooked weight through this yield (anyone's), or None. Logged entries don't count:
    they keep the nutrients worked out when they were logged."""
    uses = [(_count(db, RecipeIngredient.yield_id, yield_id), "recipe ingredient"),
            (_count(db, PlanItem.yield_id, yield_id), "plan item"),
            (_count(db, SavedMealItem.yield_id, yield_id), "saved-meal item")]
    found = [f"{n} {what}{'s' if n != 1 else ''}" for n, what in uses if n]
    return ", ".join(found) or None


def food_uses_by_others(db: Session, food_id: int, user: User) -> str | None:
    """Other people's plan items and saved meals that would vanish with this (shared) food, or None."""
    plans = db.scalar(select(func.count()).where(PlanItem.food_id == food_id, PlanItem.user_id != user.id)) or 0
    meals = db.scalar(select(func.count()).select_from(SavedMealItem).join(SavedMeal)
                      .where(SavedMealItem.food_id == food_id, SavedMeal.owner_id != user.id)) or 0
    found = [f"{n} {what}{'s' if n != 1 else ''}" for n, what in ((plans, "plan item"), (meals, "saved-meal item")) if n]
    return ", ".join(found) or None


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


def form_factors(db: Session, user: User, food: Food) -> dict[str, tuple[str, float, str]]:
    """The user's chosen conversions for this food's unconverted components."""
    components = {c["name"]: c for c in food.other_components or [] if c.get("nutrient_code")}
    if not components:
        return {}
    out = {}
    for choice in db.scalars(select(FormChoice).where(FormChoice.user_id == user.id, FormChoice.food_id == food.id)):
        comp = components.get(choice.component_name)
        opt = option(choice.nutrient_code, comp.get("unit") or "", choice.option_key) if comp else None
        if opt:
            out[choice.component_name] = (choice.nutrient_code, opt.factor, opt.label.lower())
    return out
