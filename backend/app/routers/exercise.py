from datetime import date, timedelta

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import Exercise, User
from app.schemas import ExerciseIn, ExerciseOut
from app.security import current_user
from app.services import exercise as svc
from app.services.summary import local_date, local_today

router = APIRouter(prefix="/api/exercise", tags=["exercise"])

MAX_REPORTED_ERRORS = 50


def _own(db: Session, user: User, exercise_id: int) -> Exercise:
    ex = db.get(Exercise, exercise_id)
    if ex is None or ex.user_id != user.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Exercise not found")
    return ex


def _apply(db: Session, user: User, ex: Exercise, body: ExerciseIn) -> None:
    if body.date > local_today(user):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "Can't record exercise for a future date")
    activity = svc.compendium().get(body.activity_code) if body.activity_code else None
    if body.activity_code and activity is None:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "Unknown activity code")
    name = body.name.strip() or (activity.description if activity else "")
    if not name:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "Choose an activity or give the exercise a name")
    # An imported device figure stays "device" until someone changes it.
    reported_by = "device" if ex.source != "manual" and body.reported_kcal == ex.reported_kcal else "entered"
    for key, value in body.model_dump().items():
        setattr(ex, key, value)
    ex.name = name
    ex.met = activity.met if activity else None
    ex.weight_kg = svc.weight_on(db, user, body.date)
    for key, value in svc.estimate(ex.met, body.duration_min, ex.weight_kg, body.reported_kcal, reported_by).items():
        setattr(ex, key, value)


@router.get("", response_model=list[ExerciseOut])
def list_exercise(start: date | None = None, end: date | None = None, user: User = Depends(current_user),
                  db: Session = Depends(get_db)):
    end = end or local_today(user)
    start = start or end - timedelta(days=29)
    return list(db.scalars(select(Exercise).where(Exercise.user_id == user.id, Exercise.date >= start,
                                                  Exercise.date <= end)
                           .order_by(Exercise.date.desc(), Exercise.started_at.desc(), Exercise.id.desc())))


@router.get("/activities")
def activities(q: str = "", limit: int = Query(30, ge=1, le=100), user: User = Depends(current_user)):
    """Search the 2024 Adult Compendium of Physical Activities (common activities when q is empty)."""
    return [{"code": a.code, "met": a.met, "heading": a.heading, "description": a.description}
            for a in svc.search_activities(q, limit)]


@router.post("", response_model=ExerciseOut, status_code=201)
def add_exercise(body: ExerciseIn, user: User = Depends(current_user), db: Session = Depends(get_db)):
    ex = Exercise(user_id=user.id, source="manual")
    _apply(db, user, ex, body)
    db.add(ex)
    db.commit()
    return ex


@router.put("/{exercise_id}", response_model=ExerciseOut)
def update_exercise(exercise_id: int, body: ExerciseIn, user: User = Depends(current_user),
                    db: Session = Depends(get_db)):
    ex = _own(db, user, exercise_id)
    _apply(db, user, ex, body)
    db.commit()
    return ex


@router.delete("/{exercise_id}", status_code=204)
def delete_exercise(exercise_id: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    db.delete(_own(db, user, exercise_id))
    db.commit()


def _uploads(files: list[UploadFile]):
    """(file name, bytes or error) for each activity file, opening .zip archives."""
    for upload in files:
        name = upload.filename or "upload"
        if name.lower().endswith(".zip"):
            try:
                yield from svc.iter_archive(upload.file)
            except svc.ActivityFileError as exc:
                yield name, exc
        else:
            try:
                yield name, svc.read_limited(upload.file)
            except svc.ActivityFileError as exc:
                yield name, exc


@router.post("/import")
def import_files(files: list[UploadFile] = File(...), since: date | None = Form(None),
                 user: User = Depends(current_user), db: Session = Depends(get_db)):
    """Import workouts from .fit, .tcx or .gpx files (optionally .gz), or a .zip of them such as a Strava export."""
    seen = set(db.scalars(select(Exercise.external_id).where(Exercise.user_id == user.id,
                                                             Exercise.external_id.is_not(None))))
    imported: list[Exercise] = []
    duplicates = before = 0
    errors: list[dict] = []
    for name, data in _uploads(files):
        try:
            if isinstance(data, Exception):
                raise data
            parsed = svc.parse_file(name, data)
        except svc.ActivityFileError as exc:
            errors.append({"file": name, "error": str(exc)})
            continue
        if not parsed:
            errors.append({"file": name, "error": "No workout found in the file"})
        for act in parsed:
            day = local_date(user, act.started_at)
            key = svc.external_id(act.started_at)
            if since and day < since:
                before += 1
                continue
            if key in seen:
                duplicates += 1
                continue
            seen.add(key)
            activity = svc.activity_for_sport(act.sport, act.sub_sport)
            weight = svc.weight_on(db, user, day)
            ex = Exercise(
                user_id=user.id, date=day, started_at=act.started_at, source=act.source, external_id=key,
                name=activity.description if activity else (act.sport or "Workout").replace("_", " ").capitalize(),
                activity_code=activity.code if activity else None, met=activity.met if activity else None,
                duration_min=round(act.duration_min, 2), distance_m=act.distance_m and round(act.distance_m, 1),
                avg_hr=act.avg_hr and round(act.avg_hr), reported_kcal=act.reported_kcal, weight_kg=weight,
                note="", **svc.estimate(activity.met if activity else None, act.duration_min, weight, act.reported_kcal))
            db.add(ex)
            imported.append(ex)
    db.commit()
    return {
        "imported": len(imported), "skipped_duplicates": duplicates, "skipped_before_since": before,
        "errors": errors[:MAX_REPORTED_ERRORS], "error_count": len(errors),
        "exercises": [ExerciseOut.model_validate(e).model_dump(mode="json") for e in imported[:200]],
    }
