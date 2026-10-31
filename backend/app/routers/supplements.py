from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import User
from app.security import current_user, reads_only
from app.services import supplement_check
from app.services.access import get_food

router = APIRouter(prefix="/api/supplements", tags=["supplements"])


class CheckIn(BaseModel):
    food_id: int
    servings_per_day: float | None = Field(default=None, gt=0, le=100)  # None: the usual dose if already taken, else 1
    days: int = Field(default=14, ge=3, le=90)


@router.post("/check")
@reads_only
def check_supplement(body: CheckIn, user: User = Depends(current_user), db: Session = Depends(get_db)):
    food = get_food(db, user, body.food_id)
    try:
        return supplement_check.check(db, user, food, body.servings_per_day, body.days)
    except ValueError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc)) from exc


@router.get("/stack")
def supplement_stack(days: int = Query(14, ge=3, le=90), user: User = Depends(current_user), db: Session = Depends(get_db)):
    return supplement_check.stack(db, user, days)
