from datetime import UTC, datetime, timedelta

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerifyMismatchError
from fastapi import Depends, HTTPException, Request, Response, status
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db import get_db
from app.models import ProfileShare, User

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


def signed_in_user(request: Request, db: Session = Depends(get_db)) -> User:
    """The person signed in. Use for their account, admin rights and who-can-see-what settings."""
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


# The profile a request works on, when it isn't the signed-in user's own (see current_user).
PROFILE_HEADER = "X-Mealplan-Profile"
# Set on the refusal when that profile isn't shared with them (any more), so the UI can switch back.
PROFILE_GONE_HEADER = "X-Mealplan-Profile-Gone"
_SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}


def current_user(request: Request, user: User = Depends(signed_in_user), db: Session = Depends(get_db)) -> User:
    """Whose data the request works on: the signed-in user, or someone who shared their profile with
    them (named by the profile header). With view-only access, only reads are allowed."""
    raw = request.headers.get(PROFILE_HEADER)
    if not raw:
        return user
    try:
        owner_id = int(raw)
    except ValueError:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, f"{PROFILE_HEADER} must be a user id") from None
    if owner_id == user.id:
        return user
    share = db.get(ProfileShare, (owner_id, user.id))
    owner = db.get(User, owner_id) if share else None
    if share is None or owner is None or not owner.is_active:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "That profile isn't shared with you any more",
                            headers={PROFILE_GONE_HEADER: "1"})
    writes = request.method not in _SAFE_METHODS and not getattr(request.scope.get("endpoint"), "reads_only", False)
    if writes and not share.can_edit:
        name = owner.display_name or owner.email
        raise HTTPException(status.HTTP_403_FORBIDDEN, f"{name} shared their profile with you to view only")
    return owner


def reads_only(endpoint):
    """Mark a POST endpoint that changes nothing (a calculation), so view-only profile access may use it."""
    endpoint.reads_only = True
    return endpoint


def own_profile_user(user: User = Depends(current_user), me: User = Depends(signed_in_user)) -> User:
    """The signed-in user, refusing requests made while using someone else's profile: for settings
    that only the profile's owner may change, such as who can see their plan."""
    if user.id != me.id:
        raise HTTPException(status.HTTP_403_FORBIDDEN, f"Only {user.display_name or user.email} can change this")
    return me


def admin_user(user: User = Depends(signed_in_user)) -> User:
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
