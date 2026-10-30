from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import Profile, User
from app.schemas import LoginIn, RegisterIn, UserOut
from app.security import clear_session, current_user, hash_password, issue_session, verify_password
from app.settings_store import runtime_settings

router = APIRouter(prefix="/api/auth", tags=["auth"])


@router.post("/register", response_model=UserOut, status_code=201)
def register(body: RegisterIn, response: Response, db: Session = Depends(get_db)):
    first_user = db.scalar(select(func.count(User.id))) == 0
    if not first_user and not runtime_settings(db).allow_registration:  # the first (admin) account is always allowed
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Sign-ups are closed; ask an admin for an account")
    user = User(email=body.email.lower(), password_hash=hash_password(body.password),
                display_name=body.display_name, is_admin=first_user)
    user.profile = Profile()
    db.add(user)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status.HTTP_409_CONFLICT, "An account with that email already exists") from None
    issue_session(response, user)
    return user


@router.post("/login", response_model=UserOut)
def login(body: LoginIn, response: Response, db: Session = Depends(get_db)):
    user = db.scalar(select(User).where(User.email == body.email.lower()))
    if user is None or not user.is_active or not verify_password(user.password_hash, body.password):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Incorrect email or password")
    issue_session(response, user)
    return user


@router.post("/logout", status_code=204)
def logout(response: Response):
    clear_session(response)


@router.get("/me", response_model=UserOut)
def me(user: User = Depends(current_user)):
    return user
