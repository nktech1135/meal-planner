import logging
import secrets
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import Profile, User
from app.schemas import LoginIn, RegisterIn, UserOut
from app.security import (
    burn_password_check,
    clear_session,
    hash_password,
    issue_session,
    login_throttle,
    signed_in_user,
    verify_password,
)
from app.services.accounts import consume_reset_token, end_sessions, new_reset_token, reset_link, revoke_reset_tokens
from app.services.mail import MailError, links_by_email, send_mail
from app.settings_store import runtime_settings

log = logging.getLogger(__name__)

router = APIRouter(prefix="/api/auth", tags=["auth"])

# Failed sign-ins allowed per address, and per address and email, in the throttle's window. An address can
# be shared (a household behind one router), so it gets more room than one email from it.
ADDRESS_LIMIT = 50


def _address(request: Request) -> str:
    return f"ip:{request.client.host if request.client else '?'}"


@router.post("/register", response_model=UserOut, status_code=201)
def register(body: RegisterIn, request: Request, response: Response, db: Session = Depends(get_db)):
    settings = runtime_settings(db)
    first_user = db.scalar(select(func.count(User.id))) == 0
    if first_user and settings.setup_code:
        # The first account becomes the admin, so claiming it takes the code the installer printed.
        login_throttle.check(f"setup:{_address(request)}")
        if not secrets.compare_digest((body.setup_code or "").strip(), settings.setup_code):
            login_throttle.fail(f"setup:{_address(request)}")
            raise HTTPException(status.HTTP_403_FORBIDDEN,
                                "Enter the setup code the installer printed (also in the server's configuration "
                                "file as SETUP_CODE)")
    if not first_user and not settings.allow_registration:  # the first (admin) account is always allowed
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Sign-ups are closed; ask an admin for an account")
    user = User(email=body.email.lower(), password_hash=hash_password(body.password),
                display_name=body.display_name, is_admin=first_user)
    user.profile = Profile(timezone=body.timezone)
    db.add(user)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status.HTTP_409_CONFLICT, "An account with that email already exists") from None
    issue_session(response, user, db)
    return user


@router.post("/login", response_model=UserOut)
def login(body: LoginIn, request: Request, response: Response, db: Session = Depends(get_db)):
    address = _address(request)
    pair = f"{address}|email:{body.email.lower()}"
    login_throttle.check(address, limit=ADDRESS_LIMIT)
    login_throttle.check(pair)
    user = db.scalar(select(User).where(User.email == body.email.lower()))
    if user is None:
        burn_password_check(body.password)
    if user is None or not verify_password(user.password_hash, body.password) or not user.is_active:
        login_throttle.fail(address, pair)
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Incorrect email or password")
    login_throttle.clear(pair)
    user.last_login_at = datetime.now(UTC)
    issue_session(response, user, db)
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
    if user and user.is_active and links_by_email(settings):
        # Earlier links stay valid, so a stranger asking for one can't cancel the link the person is using.
        link = reset_link(settings, None, new_reset_token(db, user, revoke_earlier=False))
        try:
            send_mail(settings, user.email, "Reset your Mealplan password",
                      f"Someone (hopefully you) asked to reset the password for {user.email}.\n\n"
                      f"Open this link within 24 hours to choose a new password:\n{link}\n\n"
                      "If you didn't ask for this, you can ignore this email.")
        except MailError:
            log.exception("Password reset email failed")
    return {"email_enabled": links_by_email(settings)}


@router.post("/reset", response_model=UserOut)
def reset_password(body: ResetIn, response: Response, db: Session = Depends(get_db)):
    user = consume_reset_token(db, body.token)
    user.password_hash = hash_password(body.new_password)
    end_sessions(user)
    revoke_reset_tokens(db, user)
    issue_session(response, user, db)
    return user


@router.post("/logout", status_code=204)
def logout(request: Request, response: Response, db: Session = Depends(get_db)):
    clear_session(request, response, db)


@router.get("/me", response_model=UserOut)
def me(user: User = Depends(signed_in_user)):
    return user
