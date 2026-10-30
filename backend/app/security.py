from datetime import UTC, datetime, timedelta

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerifyMismatchError
from fastapi import Depends, HTTPException, Request, Response, status
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db import get_db
from app.models import User

_hasher = PasswordHasher()
_ALGORITHM = "HS256"


def hash_password(password: str) -> str:
    return _hasher.hash(password)


def verify_password(password_hash: str, password: str) -> bool:
    try:
        return _hasher.verify(password_hash, password)
    except (VerifyMismatchError, InvalidHashError):
        return False


def issue_session(response: Response, user: User) -> None:
    settings = get_settings()
    expires = datetime.now(UTC) + timedelta(hours=settings.session_ttl_hours)
    token = jwt.encode({"sub": str(user.id), "sv": user.session_version or 0, "exp": expires}, settings.secret_key,
                       algorithm=_ALGORITHM)
    response.set_cookie(
        settings.session_cookie_name,
        token,
        max_age=settings.session_ttl_hours * 3600,
        httponly=True,
        secure=settings.cookie_secure,
        samesite="lax",
        path="/",
    )


def clear_session(response: Response) -> None:
    response.delete_cookie(get_settings().session_cookie_name, path="/")


def current_user(request: Request, db: Session = Depends(get_db)) -> User:
    settings = get_settings()
    unauthorized = HTTPException(status.HTTP_401_UNAUTHORIZED, "Not signed in")
    token = request.cookies.get(settings.session_cookie_name)
    if not token:
        raise unauthorized
    try:
        payload = jwt.decode(token, settings.secret_key, algorithms=[_ALGORITHM])
        user_id = int(payload["sub"])
    except (jwt.PyJWTError, KeyError, ValueError):
        raise unauthorized from None
    user = db.get(User, user_id)
    if user is None or not user.is_active or payload.get("sv", 0) != (user.session_version or 0):
        raise unauthorized
    return user


def admin_user(user: User = Depends(current_user)) -> User:
    if not user.is_admin:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Admin only")
    return user


class LoginThrottle:
    """In-memory brute-force brake: too many failures for an email or address in a window → 429."""

    def __init__(self, limit: int = 10, window: timedelta = timedelta(minutes=15)):
        self.limit, self.window = limit, window
        self.failures: dict[str, list[datetime]] = {}

    def _recent(self, key: str) -> list[datetime]:
        cutoff = datetime.now(UTC) - self.window
        times = [t for t in self.failures.get(key, []) if t > cutoff]
        self.failures[key] = times
        return times

    def check(self, *keys: str) -> None:
        if any(len(self._recent(k)) >= self.limit for k in keys):
            raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, "Too many attempts; try again in 15 minutes")

    def fail(self, *keys: str) -> None:
        for k in keys:
            self._recent(k).append(datetime.now(UTC))

    def clear(self, *keys: str) -> None:
        for k in keys:
            self.failures.pop(k, None)


login_throttle = LoginThrottle()
