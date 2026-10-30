"""Shared meal plans: a user can let others see, or see and edit, their plan and shopping list.

Plan endpoints take ``?of=<user id>`` to work on someone else's plan. Everything in a plan has to be
visible to the plan's owner, so items are always checked as the owner: an editor can add shared
database foods and the owner's own foods and recipes, not their own private ones. Only the owner logs
from their plan; that writes to their food log, which isn't shared.
"""

from fastapi import Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import PlanShare, User
from app.security import current_user


def plan_owner(db: Session, user: User, owner_id: int | None, *, edit: bool) -> User:
    """The user whose plan is being read or changed, if ``user`` may do that."""
    if owner_id is None or owner_id == user.id:
        return user
    share = db.get(PlanShare, (owner_id, user.id))
    owner = db.get(User, owner_id) if share else None
    if share is None or owner is None or not owner.is_active:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "That plan hasn't been shared with you")
    if edit and not share.can_edit:
        raise HTTPException(status.HTTP_403_FORBIDDEN, f"{name_of(owner)} shared their plan with you to view only")
    return owner


def acting_user(for_user: int | None = Query(None, description="Read as the owner of a plan shared with you, "
                                                                "e.g. to pick their foods and recipes"),
                user: User = Depends(current_user), db: Session = Depends(get_db)) -> User:
    return plan_owner(db, user, for_user, edit=False)


def name_of(user: User) -> str:
    return user.display_name or user.email


def person(user: User) -> dict:
    return {"user_id": user.id, "email": user.email, "display_name": user.display_name, "name": name_of(user)}


def shares_of(db: Session, user: User) -> dict:
    granted = db.execute(select(PlanShare, User).join(User, User.id == PlanShare.member_id)
                         .where(PlanShare.owner_id == user.id).order_by(User.email)).all()
    received = db.execute(select(PlanShare, User).join(User, User.id == PlanShare.owner_id)
                          .where(PlanShare.member_id == user.id, User.is_active).order_by(User.email)).all()
    return {
        "shared_with": [{**person(u), "can_edit": s.can_edit} for s, u in granted],
        "shared_with_me": [{**person(u), "can_edit": s.can_edit} for s, u in received],
    }


def grant(db: Session, owner: User, email: str, can_edit: bool) -> dict:
    member = db.scalar(select(User).where(User.email == email.lower().strip(), User.is_active))
    if member is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No active account with that email")
    if member.id == owner.id:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "That's the plan's own account")
    share = db.get(PlanShare, (owner.id, member.id))
    if share is None:
        db.add(PlanShare(owner_id=owner.id, member_id=member.id, can_edit=can_edit))
    else:
        share.can_edit = can_edit
    db.commit()
    return shares_of(db, owner)


def revoke(db: Session, owner_id: int, member_id: int) -> None:
    share = db.get(PlanShare, (owner_id, member_id))
    if share is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Not shared")
    db.delete(share)
    db.commit()
