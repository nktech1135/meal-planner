"""Sharing: a meal plan (see app.services.sharing), or a whole profile (see app.security.current_user).

Plan sharing follows the profile in use, so someone using your profile sees the plans shared with you,
but only you can change who sees your plan. Profile access is always the signed-in person's own.
"""

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, EmailStr
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import ProfileShare, User
from app.security import admin_user, current_user, own_profile_user, signed_in_user
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
def share_my_plan(body: ShareIn, user: User = Depends(own_profile_user), db: Session = Depends(get_db)):
    return sharing.grant(db, user, body.email, body.can_edit)


@router.delete("/plan-shares/{member_id}", status_code=204)
def stop_sharing(member_id: int, user: User = Depends(own_profile_user), db: Session = Depends(get_db)):
    sharing.revoke(db, user.id, member_id)


@router.delete("/plan-shares/from/{owner_id}", status_code=204)
def leave_shared_plan(owner_id: int, user: User = Depends(own_profile_user), db: Session = Depends(get_db)):
    """Stop seeing someone else's plan."""
    sharing.revoke(db, owner_id, user.id)


@router.get("/profile-access")
def my_profile_access(user: User = Depends(signed_in_user), db: Session = Depends(get_db)):
    """Who can use my profile, and whose profiles I can use (to switch to)."""
    return sharing.shares_of(db, user, ProfileShare)


@router.put("/profile-access")
def share_my_profile(body: ShareIn, user: User = Depends(signed_in_user), db: Session = Depends(get_db)):
    return sharing.grant(db, user, body.email, body.can_edit, ProfileShare)


@router.delete("/profile-access/{member_id}", status_code=204)
def stop_sharing_profile(member_id: int, user: User = Depends(signed_in_user), db: Session = Depends(get_db)):
    sharing.revoke(db, user.id, member_id, ProfileShare)


@router.delete("/profile-access/from/{owner_id}", status_code=204)
def leave_shared_profile(owner_id: int, user: User = Depends(signed_in_user), db: Session = Depends(get_db)):
    """Give up access to someone else's profile."""
    sharing.revoke(db, owner_id, user.id, ProfileShare)


# Admins can set either up for anyone, e.g. for family members whose accounts they created.

@router.get("/admin/users/{user_id}/plan-shares")
def user_shares(user_id: int, _: User = Depends(admin_user), db: Session = Depends(get_db)):
    return sharing.shares_of(db, _target(db, user_id))


@router.put("/admin/users/{user_id}/plan-shares")
def share_users_plan(user_id: int, body: ShareIn, _: User = Depends(admin_user), db: Session = Depends(get_db)):
    return sharing.grant(db, _target(db, user_id), body.email, body.can_edit)


@router.delete("/admin/users/{user_id}/plan-shares/{member_id}", status_code=204)
def unshare_users_plan(user_id: int, member_id: int, _: User = Depends(admin_user), db: Session = Depends(get_db)):
    sharing.revoke(db, _target(db, user_id).id, member_id)


@router.get("/admin/users/{user_id}/profile-access")
def user_profile_access(user_id: int, _: User = Depends(admin_user), db: Session = Depends(get_db)):
    return sharing.shares_of(db, _target(db, user_id), ProfileShare)


@router.put("/admin/users/{user_id}/profile-access")
def share_users_profile(user_id: int, body: ShareIn, _: User = Depends(admin_user), db: Session = Depends(get_db)):
    return sharing.grant(db, _target(db, user_id), body.email, body.can_edit, ProfileShare)


@router.delete("/admin/users/{user_id}/profile-access/{member_id}", status_code=204)
def unshare_users_profile(user_id: int, member_id: int, _: User = Depends(admin_user), db: Session = Depends(get_db)):
    sharing.revoke(db, _target(db, user_id).id, member_id, ProfileShare)


def _target(db: Session, user_id: int) -> User:
    u = db.get(User, user_id)
    if u is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "User not found")
    return u
