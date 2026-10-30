from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, EmailStr
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import User
from app.security import admin_user, current_user
from app.services import sharing

router = APIRouter(prefix="/api", tags=["sharing"])


class ShareIn(BaseModel):
    email: EmailStr
    can_edit: bool = True


@router.get("/plan-shares")
def my_shares(user: User = Depends(current_user), db: Session = Depends(get_db)):
    """Who can see my plan, and whose plans I can see."""
    return sharing.shares_of(db, user)


@router.put("/plan-shares")
def share_my_plan(body: ShareIn, user: User = Depends(current_user), db: Session = Depends(get_db)):
    return sharing.grant(db, user, body.email, body.can_edit)


@router.delete("/plan-shares/{member_id}", status_code=204)
def stop_sharing(member_id: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    sharing.revoke(db, user.id, member_id)


@router.delete("/plan-shares/from/{owner_id}", status_code=204)
def leave_shared_plan(owner_id: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    """Stop seeing someone else's plan."""
    sharing.revoke(db, owner_id, user.id)


# Admins can set this up for anyone, e.g. for family members whose accounts they created.

@router.get("/admin/users/{user_id}/plan-shares")
def user_shares(user_id: int, _: User = Depends(admin_user), db: Session = Depends(get_db)):
    return sharing.shares_of(db, _target(db, user_id))


@router.put("/admin/users/{user_id}/plan-shares")
def share_users_plan(user_id: int, body: ShareIn, _: User = Depends(admin_user), db: Session = Depends(get_db)):
    return sharing.grant(db, _target(db, user_id), body.email, body.can_edit)


@router.delete("/admin/users/{user_id}/plan-shares/{member_id}", status_code=204)
def unshare_users_plan(user_id: int, member_id: int, _: User = Depends(admin_user), db: Session = Depends(get_db)):
    sharing.revoke(db, _target(db, user_id).id, member_id)


def _target(db: Session, user_id: int) -> User:
    u = db.get(User, user_id)
    if u is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "User not found")
    return u
