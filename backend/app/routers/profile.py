from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import Profile, User
from app.schemas import ProfileIn, ProfileOut
from app.security import current_user
from app.services.summary import local_today
from app.services.targets import compute_targets

router = APIRouter(prefix="/api", tags=["profile"])


def _profile(db: Session, user: User) -> Profile:
    if user.profile is None:
        user.profile = Profile()
        db.commit()
    return user.profile


@router.get("/profile", response_model=ProfileOut)
def get_profile(user: User = Depends(current_user), db: Session = Depends(get_db)):
    return _profile(db, user)


@router.put("/profile", response_model=ProfileOut)
def put_profile(body: ProfileIn, user: User = Depends(current_user), db: Session = Depends(get_db)):
    profile = _profile(db, user)
    for key, value in body.model_dump().items():
        setattr(profile, key, value)
    db.commit()
    return profile


@router.get("/targets")
def get_targets(user: User = Depends(current_user), db: Session = Depends(get_db)):
    return compute_targets(_profile(db, user), local_today(user))
