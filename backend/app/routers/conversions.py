from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import CookingYield, RetentionProfile, User
from app.nutrients import Trust, weakest
from app.schemas import CalculateIn, DeriveIn, NutritionOut, YieldIn, YieldOut
from app.security import current_user
from app.services.access import form_factors, get_food, get_recipe, get_yield, recipe_yields, visible
from app.services.nutrition import NutritionError, derive_yield, food_nutrition, recipe_portion

router = APIRouter(prefix="/api", tags=["conversions"])


@router.get("/foods/{food_id}/yields", response_model=list[YieldOut])
def list_yields(food_id: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    get_food(db, user, food_id)
    return list(db.scalars(
        select(CookingYield).where(CookingYield.raw_food_id == food_id, visible(CookingYield, user))
        .order_by(CookingYield.method)
    ))


@router.post("/yields", response_model=YieldOut, status_code=201)
def create_yield(body: YieldIn, user: User = Depends(current_user), db: Session = Depends(get_db)):
    raw = get_food(db, user, body.raw_food_id)
    cooked = get_food(db, user, body.cooked_food_id) if body.cooked_food_id else None
    notes = body.notes
    trust = Trust.USER
    if body.basis == "derived":
        # Computed here rather than accepted from the client, so the trust level reflects the source data.
        if cooked is None:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "Derived yields need the cooked food")
        try:
            derived = derive_yield(raw, cooked)
        except NutritionError as exc:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc)) from None
        factor = derived["yield_factor"]
        trust = weakest([derived["trust_level"], Trust.USER if body.retention else None])
        notes = (notes + " " if notes else "") + derived["method_note"]
    elif body.raw_weight_g and body.cooked_weight_g:
        factor = body.cooked_weight_g / body.raw_weight_g
        notes = (notes + " " if notes else "") + f"Measured: {body.raw_weight_g:g} g raw → {body.cooked_weight_g:g} g cooked."
    else:
        factor = body.yield_factor
    if factor is None:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "Give a yield factor or raw and cooked weights")
    if body.basis == "published" and not body.citation:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "Published yields need a citation")
    retention, citation = body.retention, body.citation
    if body.retention_profile_code is not None:
        profile = db.get(RetentionProfile, body.retention_profile_code)
        if profile is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Unknown retention profile")
        retention = profile.factors
        ref = f"Retention factors: USDA Table of Nutrient Retention Factors, {profile.release}, {profile.description}."
        citation = f"{citation} {ref}" if citation else ref
    y = CookingYield(
        raw_food_id=raw.id, cooked_food_id=cooked.id if cooked else None, method=body.method, yield_factor=factor,
        retention=retention, basis=body.basis, trust_level=trust, citation=citation, notes=notes,
        owner_id=user.id,
    )
    db.add(y)
    db.commit()
    return y


@router.delete("/yields/{yield_id}", status_code=204)
def delete_yield(yield_id: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    y = get_yield(db, user, yield_id)
    if y.owner_id != user.id and not user.is_admin:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Not allowed")
    db.delete(y)
    db.commit()


@router.post("/yields/derive")
def derive(body: DeriveIn, user: User = Depends(current_user), db: Session = Depends(get_db)):
    try:
        return derive_yield(get_food(db, user, body.raw_food_id), get_food(db, user, body.cooked_food_id))
    except NutritionError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc)) from None


def calculate_nutrition(db: Session, user: User, body) -> NutritionOut:
    """Shared by the calculator endpoint and the food log."""
    try:
        if body.recipe_id:
            recipe = get_recipe(db, user, body.recipe_id)
            result = recipe_portion(recipe, recipe_yields(db, user, recipe), body.quantity, body.unit)
        elif body.food_id:
            food = get_food(db, user, body.food_id)
            y = get_yield(db, user, body.yield_id) if body.yield_id else None
            result = food_nutrition(food, body.quantity, body.unit, body.weighed_state, y, form_factors(db, user, food))
        else:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "Give a food_id or recipe_id")
    except NutritionError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc)) from None
    return NutritionOut(**result.__dict__)


@router.post("/nutrition/calculate", response_model=NutritionOut)
def calculate(body: CalculateIn, user: User = Depends(current_user), db: Session = Depends(get_db)):
    return calculate_nutrition(db, user, body)


# SR food group codes used by the retention table.
FOOD_GROUPS = {
    1: "Dairy and Egg Products", 5: "Poultry Products", 8: "Breakfast Cereals", 9: "Fruits and Fruit Juices",
    10: "Pork Products", 11: "Vegetables and Vegetable Products", 12: "Nut and Seed Products", 13: "Beef Products",
    14: "Beverages", 15: "Finfish and Shellfish Products", 16: "Legumes and Legume Products",
    17: "Lamb, Veal, and Game Products", 20: "Cereal Grains and Pasta",
}
GROUP_BY_CATEGORY = {v: k for k, v in FOOD_GROUPS.items()}


@router.get("/retention-profiles")
def retention_profiles(q: str = "", food_id: int | None = None, user: User = Depends(current_user),
                       db: Session = Depends(get_db)):
    """USDA retention profiles, optionally narrowed to the food group of ``food_id``."""
    stmt = select(RetentionProfile).order_by(RetentionProfile.food_group, RetentionProfile.description)
    group = None
    if food_id is not None:
        group = GROUP_BY_CATEGORY.get(get_food(db, user, food_id).category or "")
        if group is not None:
            stmt = stmt.where(RetentionProfile.food_group == group)
    for term in q.upper().split():
        stmt = stmt.where(RetentionProfile.description.ilike(f"%{term}%"))
    return {
        "food_group": FOOD_GROUPS.get(group) if group else None,
        "profiles": [{"code": p.code, "description": p.description, "food_group": FOOD_GROUPS.get(p.food_group),
                      "factors": p.factors, "release": p.release} for p in db.scalars(stmt.limit(200))],
    }
