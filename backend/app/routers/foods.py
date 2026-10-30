from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import Food, FoodNutrient, FoodPortion, User
from app.nutrients import MACRO_CODES, NUTRIENTS, Trust
from app.schemas import FoodIn, FoodOut, FoodSummary, NutrientDefOut
from app.security import current_user
from app.services.access import get_food, visible

router = APIRouter(prefix="/api", tags=["foods"])


def food_summary(food: Food) -> FoodSummary:
    nm = food.nutrient_map()
    out = FoodSummary.model_validate(food)
    out.macros = {c: round(nm[c], 2) for c in MACRO_CODES if c in nm}
    return out


def food_out(food: Food) -> FoodOut:
    base = food_summary(food).model_dump()
    return FoodOut(
        **base,
        source_id=food.source_id, source_url=food.source_url, citation=food.citation,
        fetched_at=food.fetched_at, created_at=food.created_at,
        nutrients={n.nutrient_code: n.amount for n in food.nutrients},
        derivations={n.nutrient_code: n.derivation for n in food.nutrients},
        portions=food.portions, other_components=food.other_components or [],
    )


@router.get("/nutrients", response_model=list[NutrientDefOut])
def list_nutrients():
    return [NutrientDefOut(code=n.code, name=n.name, unit=n.unit, category=n.category) for n in NUTRIENTS]


@router.get("/foods", response_model=list[FoodSummary])
def search_foods(
    q: str = "",
    kind: str | None = None,
    mine: bool = False,
    limit: int = Query(50, le=200),
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
):
    stmt = select(Food).where(Food.owner_id == user.id if mine else visible(Food, user))
    for term in q.split():
        like = f"%{term}%"
        stmt = stmt.where(or_(Food.name.ilike(like), Food.brand.ilike(like)))
    if kind:
        stmt = stmt.where(Food.kind == kind)
    stmt = stmt.order_by(Food.name).limit(limit)
    return [food_summary(f) for f in db.scalars(stmt)]


@router.get("/foods/{food_id}", response_model=FoodOut)
def read_food(food_id: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    return food_out(get_food(db, user, food_id))


def _apply(food: Food, body: FoodIn, db: Session) -> None:
    for key in ("name", "brand", "kind", "state", "cooking_method", "basis", "serving_quantity",
                "serving_unit", "serving_size_g", "citation"):
        setattr(food, key, getattr(body, key))
    food.other_components = [c.model_dump() for c in body.other_components]
    food.nutrients.clear()
    food.portions.clear()
    db.flush()
    food.nutrients = [FoodNutrient(nutrient_code=c, amount=a, derivation="User entered") for c, a in body.nutrients.items()]
    food.portions = [FoodPortion(label=p.label, gram_weight=p.gram_weight) for p in body.portions]


@router.post("/foods", response_model=FoodOut, status_code=201)
def create_food(body: FoodIn, user: User = Depends(current_user), db: Session = Depends(get_db)):
    food = Food(owner_id=user.id, source="manual", trust_level=Trust.USER)
    db.add(food)
    _apply(food, body, db)
    db.commit()
    db.refresh(food)
    return food_out(food)


def _own(db: Session, user: User, food_id: int) -> Food:
    food = get_food(db, user, food_id)
    if food.owner_id != user.id:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Imported foods are read-only; copy it to edit")
    return food


@router.put("/foods/{food_id}", response_model=FoodOut)
def update_food(food_id: int, body: FoodIn, user: User = Depends(current_user), db: Session = Depends(get_db)):
    food = _own(db, user, food_id)
    _apply(food, body, db)
    db.commit()
    db.refresh(food)
    return food_out(food)


@router.post("/foods/{food_id}/copy", response_model=FoodOut, status_code=201)
def copy_food(food_id: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    """Make an editable private copy. The copy is user data, citing the original."""
    src = get_food(db, user, food_id)
    food = Food(
        owner_id=user.id, source="manual", trust_level=Trust.USER, name=f"{src.name} (copy)", brand=src.brand,
        kind=src.kind, state=src.state, cooking_method=src.cooking_method, basis=src.basis,
        serving_quantity=src.serving_quantity, serving_unit=src.serving_unit, serving_size_g=src.serving_size_g,
        citation=f"Copied from {src.citation or src.source} and possibly edited.",
        other_components=list(src.other_components or []),
        nutrients=[FoodNutrient(nutrient_code=n.nutrient_code, amount=n.amount, derivation=n.derivation) for n in src.nutrients],
        portions=[FoodPortion(label=p.label, gram_weight=p.gram_weight) for p in src.portions],
    )
    db.add(food)
    db.commit()
    db.refresh(food)
    return food_out(food)


@router.delete("/foods/{food_id}", status_code=204)
def delete_food(food_id: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    food = get_food(db, user, food_id)
    if food.owner_id != user.id and not (food.owner_id is None and user.is_admin):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Not allowed")
    db.delete(food)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status.HTTP_409_CONFLICT, "Food is used in a recipe; remove it there first") from None
