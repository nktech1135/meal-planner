import hashlib
import secrets
from datetime import UTC, datetime, timedelta

from fastapi import HTTPException, Request, status
from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from app.config import Settings
from app.models import PasswordReset, Recipe, User

RESET_TTL = timedelta(hours=24)


def _hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def new_reset_token(db: Session, user: User) -> str:
    """A fresh one-time token; earlier unused tokens for the user are revoked."""
    db.execute(delete(PasswordReset).where(PasswordReset.user_id == user.id, PasswordReset.used_at.is_(None)))
    token = secrets.token_urlsafe(32)
    db.add(PasswordReset(user_id=user.id, token_hash=_hash(token), expires_at=datetime.now(UTC) + RESET_TTL))
    db.commit()
    return token


def consume_reset_token(db: Session, token: str) -> User:
    row = db.scalar(select(PasswordReset).where(PasswordReset.token_hash == _hash(token)))
    expires = row.expires_at if row and row.expires_at.tzinfo else (row.expires_at.replace(tzinfo=UTC) if row else None)
    if row is None or row.used_at is not None or expires < datetime.now(UTC):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "This link is invalid or has expired; ask for a new one")
    user = db.get(User, row.user_id)
    if user is None or not user.is_active:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "This account is not active")
    row.used_at = datetime.now(UTC)
    return user


def reset_link(settings: Settings, request: Request, token: str) -> str:
    base = (settings.public_url or str(request.base_url)).rstrip("/")
    return f"{base}/reset-password?token={token}"


def end_sessions(user: User) -> None:
    user.session_version = (user.session_version or 0) + 1


def is_last_admin(db: Session, user: User) -> bool:
    return user.is_admin and db.scalar(select(func.count(User.id)).where(User.is_admin, User.is_active)) <= 1


def delete_user(db: Session, user: User) -> None:
    if is_last_admin(db, user):
        raise HTTPException(status.HTTP_409_CONFLICT, "This is the only admin account; make someone else admin first")
    # Recipes first: their ingredients restrict deleting the user's own foods.
    db.execute(delete(Recipe).where(Recipe.owner_id == user.id))
    db.delete(user)
    db.commit()
