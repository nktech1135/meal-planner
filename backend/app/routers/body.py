from datetime import date, timedelta

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import BodyMeasurement, Profile, User
from app.schemas import BodyIn, BodyOut
from app.security import current_user
from app.services.summary import local_today
from app.services.trends import trends

router = APIRouter(prefix="/api", tags=["body & trends"])


def _sync_profile_weight(db: Session, user: User) -> None:
    """Keep the profile's weight (used for targets) equal to the latest weigh-in."""
    latest = db.scalar(select(BodyMeasurement).where(BodyMeasurement.user_id == user.id,
                                                     BodyMeasurement.weight_kg.is_not(None))
                       .order_by(BodyMeasurement.date.desc()).limit(1))
    if latest:
        if user.profile is None:
            user.profile = Profile()
        user.profile.weight_kg = latest.weight_kg


@router.get("/body", response_model=list[BodyOut])
def list_body(start: date | None = None, end: date | None = None, user: User = Depends(current_user),
              db: Session = Depends(get_db)):
    end = end or local_today(user)
    start = start or end - timedelta(days=89)
    return list(db.scalars(select(BodyMeasurement).where(
        BodyMeasurement.user_id == user.id, BodyMeasurement.date >= start, BodyMeasurement.date <= end)
        .order_by(BodyMeasurement.date)))


@router.put("/body/{day}", response_model=BodyOut)
def put_body(day: date, body: BodyIn, user: User = Depends(current_user), db: Session = Depends(get_db)):
    if day > local_today(user):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "Can't record measurements for a future date")
    if body.weight_kg is None and body.body_fat_pct is None and body.waist_cm is None:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "Enter at least one measurement")
    m = db.scalar(select(BodyMeasurement).where(BodyMeasurement.user_id == user.id, BodyMeasurement.date == day))
    if m is None:
        m = BodyMeasurement(user_id=user.id, date=day)
        db.add(m)
    for key, value in body.model_dump().items():
        setattr(m, key, value)
    db.flush()
    _sync_profile_weight(db, user)
    db.commit()
    return m


@router.delete("/body/{day}", status_code=204)
def delete_body(day: date, user: User = Depends(current_user), db: Session = Depends(get_db)):
    m = db.scalar(select(BodyMeasurement).where(BodyMeasurement.user_id == user.id, BodyMeasurement.date == day))
    if m is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No measurements for that date")
    db.delete(m)
    db.flush()
    _sync_profile_weight(db, user)
    db.commit()


@router.get("/trends")
def get_trends(days: int = Query(30, ge=2, le=366), end: date | None = None, user: User = Depends(current_user),
               db: Session = Depends(get_db)):
    end = end or local_today(user)
    return trends(db, user, end - timedelta(days=days - 1), end)
