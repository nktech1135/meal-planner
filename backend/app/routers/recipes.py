from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import Recipe, RecipeIngredient, User
from app.schemas import RecipeIn, RecipeOut
from app.security import current_user
from app.services.access import get_food, get_recipe, get_yield, recipe_yields
from app.services.nutrition import NutritionError, recipe_nutrition
from app.services.sharing import acting_user

router = APIRouter(prefix="/api/recipes", tags=["recipes"])


def recipe_out(db: Session, user: User, recipe: Recipe, with_nutrition: bool = True) -> RecipeOut:
    out = RecipeOut.model_validate(recipe)
    for ing_out, ing in zip(out.ingredients, recipe.ingredients, strict=True):
        ing_out.food_name = ing.food.name
    if with_nutrition:
        try:
            out.nutrition = recipe_nutrition(recipe, recipe_yields(db, user, recipe))
        except NutritionError as exc:
            out.nutrition = {"error": str(exc)}
    return out


def _apply(db: Session, user: User, recipe: Recipe, body: RecipeIn) -> None:
    recipe.name, recipe.servings, recipe.cooked_weight_g, recipe.notes = (
        body.name, body.servings, body.cooked_weight_g, body.notes)
    ingredients = []
    for pos, ing in enumerate(body.ingredients):
        food = get_food(db, user, ing.food_id)
        if ing.weighed_state == "cooked" and food.state != "cooked":
            if not ing.yield_id:
                raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT,
                                    f"'{food.name}' is weighed cooked: choose a cooking yield")
            if get_yield(db, user, ing.yield_id).raw_food_id != food.id:
                raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, f"Yield does not belong to '{food.name}'")
        ingredients.append(RecipeIngredient(position=pos, food_id=food.id, grams=ing.grams,
                                            weighed_state=ing.weighed_state, yield_id=ing.yield_id, note=ing.note))
    recipe.ingredients = ingredients


@router.get("", response_model=list[RecipeOut])
def list_recipes(user: User = Depends(acting_user), db: Session = Depends(get_db)):
    recipes = db.scalars(select(Recipe).where(Recipe.owner_id == user.id).order_by(Recipe.name))
    return [recipe_out(db, user, r) for r in recipes]


@router.get("/{recipe_id}", response_model=RecipeOut)
def read_recipe(recipe_id: int, user: User = Depends(acting_user), db: Session = Depends(get_db)):
    return recipe_out(db, user, get_recipe(db, user, recipe_id))


@router.post("", response_model=RecipeOut, status_code=201)
def create_recipe(body: RecipeIn, user: User = Depends(current_user), db: Session = Depends(get_db)):
    recipe = Recipe(owner_id=user.id)
    _apply(db, user, recipe, body)
    db.add(recipe)
    db.commit()
    db.refresh(recipe)
    return recipe_out(db, user, recipe)


@router.put("/{recipe_id}", response_model=RecipeOut)
def update_recipe(recipe_id: int, body: RecipeIn, user: User = Depends(current_user), db: Session = Depends(get_db)):
    recipe = get_recipe(db, user, recipe_id)
    _apply(db, user, recipe, body)
    db.commit()
    db.refresh(recipe)
    return recipe_out(db, user, recipe)


@router.delete("/{recipe_id}", status_code=204)
def delete_recipe(recipe_id: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    db.delete(get_recipe(db, user, recipe_id))
    db.commit()
