"""The signed-in user's own account: details, password, data export, deletion."""

import json
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, Response, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.advisor.agent import render
from app.db import get_db
from app.models import (
    AdvisorConversation,
    BodyMeasurement,
    Food,
    FormChoice,
    LogEntry,
    PlanItem,
    ProfileShare,
    Recipe,
    SavedMeal,
    User,
)
from app.routers.foods import food_out
from app.schemas import BodyOut, LogOut, ProfileOut, SavedMealOut, UserOut
from app.security import clear_session, hash_password, issue_session, signed_in_user, verify_password
from app.services.accounts import delete_user, end_sessions
from app.services.sharing import shares_of

router = APIRouter(prefix="/api/account", tags=["account"])


class AccountUpdate(BaseModel):
    display_name: str = Field(max_length=120)
    email: EmailStr
    current_password: str | None = None  # required to change the email


class PasswordChange(BaseModel):
    current_password: str
    new_password: str = Field(min_length=10, max_length=200)


class DeleteAccount(BaseModel):
    password: str


def _check_password(user: User, password: str | None) -> None:
    if not password or not verify_password(user.password_hash, password):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Current password is incorrect")


@router.put("", response_model=UserOut)
def update_account(body: AccountUpdate, user: User = Depends(signed_in_user), db: Session = Depends(get_db)):
    if body.email.lower() != user.email:
        _check_password(user, body.current_password)
        user.email = body.email.lower()
    user.display_name = body.display_name
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status.HTTP_409_CONFLICT, "That email is already in use") from None
    return user


@router.put("/password", status_code=204)
def change_password(body: PasswordChange, response: Response, user: User = Depends(signed_in_user),
                    db: Session = Depends(get_db)):
    _check_password(user, body.current_password)
    user.password_hash = hash_password(body.new_password)
    end_sessions(user)  # sign out other devices
    db.commit()
    issue_session(response, user)  # but keep this one


@router.get("/export")
def export_data(user: User = Depends(signed_in_user), db: Session = Depends(get_db)):
    """Everything this account owns, as one JSON document."""
    def rows(model, owner_col):
        return list(db.scalars(select(model).where(owner_col == user.id)))

    data = {
        "exported_at": datetime.now(UTC).isoformat(),
        "account": UserOut.model_validate(user).model_dump(),
        "profile": ProfileOut.model_validate(user.profile).model_dump(mode="json") if user.profile else None,
        "foods": [food_out(f).model_dump(mode="json") for f in rows(Food, Food.owner_id)],
        "recipes": [{"name": r.name, "servings": r.servings, "cooked_weight_g": r.cooked_weight_g, "notes": r.notes,
                     "ingredients": [{"food_id": i.food_id, "food": i.food.name, "grams": i.grams,
                                      "weighed_state": i.weighed_state, "yield_id": i.yield_id} for i in r.ingredients]}
                    for r in rows(Recipe, Recipe.owner_id)],
        "log": [LogOut.model_validate(e).model_dump(mode="json") for e in rows(LogEntry, LogEntry.user_id)],
        "saved_meals": [SavedMealOut.model_validate(m).model_dump(mode="json") for m in rows(SavedMeal, SavedMeal.owner_id)],
        "body_measurements": [BodyOut.model_validate(m).model_dump(mode="json")
                              for m in rows(BodyMeasurement, BodyMeasurement.user_id)],
        "meal_plan": [{k: (getattr(p, k).isoformat() if k == "date" else getattr(p, k)) for k in (
            "date", "meal", "label", "food_id", "recipe_id", "quantity", "unit", "weighed_state", "note")}
            for p in rows(PlanItem, PlanItem.user_id)],
        "plan_sharing": shares_of(db, user),
        "profile_access": shares_of(db, user, ProfileShare),
        "form_choices": [{"food_id": c.food_id, "component": c.component_name, "option": c.option_key}
                         for c in rows(FormChoice, FormChoice.user_id)],
        "advisor_conversations": [{"title": c.title, "messages": render(c)}
                                  for c in rows(AdvisorConversation, AdvisorConversation.user_id)],
    }
    name = f"mealplan-export-{datetime.now(UTC):%Y%m%d}.json"
    return JSONResponse(json.loads(json.dumps(data, default=str)),
                        headers={"Content-Disposition": f'attachment; filename="{name}"'})


@router.delete("", status_code=204)
def delete_account(body: DeleteAccount, response: Response, user: User = Depends(signed_in_user),
                   db: Session = Depends(get_db)):
    _check_password(user, body.password)
    delete_user(db, user)
    clear_session(response)
