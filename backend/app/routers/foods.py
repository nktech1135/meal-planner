from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel
from sqlalchemy import or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import Food, FoodNutrient, FoodPortion, FormChoice, LogEntry, User
from app.nutrients import BY_CODE, MACRO_CODES, NUTRIENTS, Trust
from app.routers.log import recalculate
from app.schemas import FoodIn, FoodOut, FoodSummary, NutrientDefOut
from app.security import current_user
from app.services.access import get_food, visible
from app.services.forms import options_for

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
        portions=food.portions, other_components=food.other_components or [], ingredients=food.ingredients,
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
    terms = q.lower().split()
    for term in terms:
        like = f"%{term}%"
        stmt = stmt.where(or_(Food.name.ilike(like), Food.brand.ilike(like)))
    if kind:
        stmt = stmt.where(Food.kind == kind)
    if not terms:
        return [food_summary(f) for f in db.scalars(stmt.order_by(Food.name).limit(limit))]
    # Branded products can outnumber everything else a hundred to one; gather basic foods and
    # products separately so the basics always reach the ranking.
    is_branded = Food.source_data_type == "Branded"
    candidates = list(db.scalars(stmt.where(or_(~is_branded, Food.source_data_type.is_(None))).limit(500)))
    candidates += list(db.scalars(stmt.where(is_branded).limit(500)))
    candidates.sort(key=lambda f: search_rank(f, terms, user.id))
    return [food_summary(f) for f in candidates[:limit]]


_TYPE_RANK = {"Foundation": 0, "SR Legacy": 1, "Survey (FNDDS)": 2}


def search_rank(food: Food, terms: list[str], user_id: int) -> tuple:
    """Lower sorts first: your own foods, generic before branded products, names starting with the
    query, whole-word matches, lab data before survey data, then shorter (less specific) names."""
    name = food.name.lower()
    words = set(name.replace(",", " ").split())
    return (
        food.owner_id != user_id,
        food.source_data_type == "Branded" or food.brand is not None,
        not name.startswith(terms[0]),
        -sum(t in words for t in terms),
        _TYPE_RANK.get(food.source_data_type or "", 3),
        len(name),
    )


@router.get("/foods/{food_id}", response_model=FoodOut)
def read_food(food_id: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    return food_out(get_food(db, user, food_id))


def _component(c) -> dict:
    out = c.model_dump(exclude_none=True)
    if c.nutrient_code:
        out["reason"] = "form" if options_for(c.nutrient_code, c.unit or "") else "unit"
    return out


def _apply(food: Food, body: FoodIn, db: Session) -> None:
    for key in ("name", "brand", "kind", "state", "cooking_method", "basis", "serving_quantity",
                "serving_unit", "serving_size_g", "citation"):
        setattr(food, key, getattr(body, key))
    food.other_components = [_component(c) for c in body.other_components]
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


class FormChoiceIn(BaseModel):
    component_name: str
    option_key: str | None  # None clears the choice


def _form_rows(db: Session, user: User, food: Food) -> list[dict]:
    chosen = {c.component_name: c.option_key for c in db.scalars(
        select(FormChoice).where(FormChoice.user_id == user.id, FormChoice.food_id == food.id))}
    rows = []
    for c in food.other_components or []:
        if c.get("reason") != "form" or c.get("amount") is None:
            continue
        rows.append({
            "component_name": c["name"], "amount": c["amount"], "unit": c.get("unit"), "nutrient_code": c["nutrient_code"],
            "nutrient_name": BY_CODE[c["nutrient_code"]].name, "chosen": chosen.get(c["name"]),
            "options": [{"key": o.key, "label": o.label, "factor": o.factor, "result": round(c["amount"] * o.factor, 3),
                         "unit": BY_CODE[c["nutrient_code"]].unit, "note": o.note, "source": o.source}
                        for o in options_for(c["nutrient_code"], c.get("unit") or "")],
        })
    return rows


@router.get("/foods/{food_id}/forms")
def list_form_choices(food_id: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    """Label amounts that need their chemical form to be counted, with the conversion options."""
    return _form_rows(db, user, get_food(db, user, food_id))


@router.put("/foods/{food_id}/forms")
def set_form_choice(food_id: int, body: FormChoiceIn, user: User = Depends(current_user), db: Session = Depends(get_db)):
    """Choose (or clear) a form, then recalculate this user's log entries for the food."""
    food = get_food(db, user, food_id)
    row = next((r for r in _form_rows(db, user, food) if r["component_name"] == body.component_name), None)
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No such unconverted component on this food")
    if body.option_key is not None and body.option_key not in {o["key"] for o in row["options"]}:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "Unknown option")
    existing = db.scalar(select(FormChoice).where(FormChoice.user_id == user.id, FormChoice.food_id == food.id,
                                                   FormChoice.component_name == body.component_name))
    if body.option_key is None:
        if existing:
            db.delete(existing)
    elif existing:
        existing.option_key = body.option_key
    else:
        db.add(FormChoice(user_id=user.id, food_id=food.id, component_name=body.component_name,
                          nutrient_code=row["nutrient_code"], option_key=body.option_key))
    db.flush()
    entries = list(db.scalars(select(LogEntry).where(LogEntry.user_id == user.id, LogEntry.food_id == food.id)))
    for entry in entries:
        recalculate(db, user, entry)
    db.commit()
    return {"forms": _form_rows(db, user, food), "recalculated_entries": len(entries)}
