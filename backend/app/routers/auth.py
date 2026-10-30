import logging
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import Profile, User
from app.schemas import LoginIn, RegisterIn, UserOut
from app.security import clear_session, current_user, hash_password, issue_session, login_throttle, verify_password
from app.services.accounts import consume_reset_token, end_sessions, new_reset_token, reset_link
from app.services.mail import MailError, mail_configured, send_mail
from app.settings_store import runtime_settings

log = logging.getLogger(__name__)

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
def login(body: LoginIn, request: Request, response: Response, db: Session = Depends(get_db)):
    keys = (f"email:{body.email.lower()}", f"ip:{request.client.host if request.client else '?'}")
    login_throttle.check(*keys)
    user = db.scalar(select(User).where(User.email == body.email.lower()))
    if user is None or not user.is_active or not verify_password(user.password_hash, body.password):
        login_throttle.fail(*keys)
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Incorrect email or password")
    login_throttle.clear(keys[0])
    user.last_login_at = datetime.now(UTC)
    db.commit()
    issue_session(response, user)
    return user


class ForgotIn(BaseModel):
    email: EmailStr


class ResetIn(BaseModel):
    token: str = Field(min_length=10, max_length=200)
    new_password: str = Field(min_length=10, max_length=200)


@router.post("/forgot", status_code=202)
def forgot_password(body: ForgotIn, request: Request, db: Session = Depends(get_db)):
    """Email a reset link if the account exists and email is set up. Always answers the same way."""
    settings = runtime_settings(db)
    login_throttle.check(f"forgot:{body.email.lower()}")
    login_throttle.fail(f"forgot:{body.email.lower()}")  # counts toward the limit either way
    user = db.scalar(select(User).where(User.email == body.email.lower()))
    if user and user.is_active and mail_configured(settings):
        link = reset_link(settings, request, new_reset_token(db, user))
        try:
            send_mail(settings, user.email, "Reset your Mealplan password",
                      f"Someone (hopefully you) asked to reset the password for {user.email}.\n\n"
                      f"Open this link within 24 hours to choose a new password:\n{link}\n\n"
                      "If you didn't ask for this, you can ignore this email.")
        except MailError:
            log.exception("Password reset email failed")
    return {"email_enabled": mail_configured(settings)}


@router.post("/reset", response_model=UserOut)
def reset_password(body: ResetIn, response: Response, db: Session = Depends(get_db)):
    user = consume_reset_token(db, body.token)
    user.password_hash = hash_password(body.new_password)
    end_sessions(user)
    db.commit()
    issue_session(response, user)
    return user


@router.post("/logout", status_code=204)
def logout(response: Response):
    clear_session(response)


@router.get("/me", response_model=UserOut)
def me(user: User = Depends(current_user)):
    return user
