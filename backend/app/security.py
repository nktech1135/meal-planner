import secrets
from datetime import UTC, datetime, timedelta

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerifyMismatchError
from fastapi import Depends, HTTPException, Request, Response, status
from sqlalchemy import delete
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db import get_db
from app.models import ProfileShare, User, UserSession

_hasher = PasswordHasher()
_ALGORITHM = "HS256"


def hash_password(password: str) -> str:
    return _hasher.hash(password)


def verify_password(password_hash: str, password: str) -> bool:
    try:
        return _hasher.verify(password_hash, password)
    except (VerifyMismatchError, InvalidHashError):
        return False


_dummy_hash: str | None = None


def burn_password_check(password: str) -> None:
    """Spend as long as a real password check, so a login for an unknown email takes as long as one for a
    known email and doesn't reveal which emails have accounts."""
    global _dummy_hash
    if _dummy_hash is None:
        _dummy_hash = _hasher.hash(secrets.token_urlsafe(16))
    verify_password(_dummy_hash, password)


def issue_session(response: Response, user: User, db: Session) -> None:
    """Sign this browser in: records the session (committing) and sets its cookie."""
    from app.settings_store import runtime_settings  # imports the models, so not at the top

    settings = runtime_settings(db)
    now = datetime.now(UTC)
    expires = now + timedelta(hours=settings.session_ttl_hours)
    sid = secrets.token_urlsafe(32)
    db.execute(delete(UserSession).where(UserSession.expires_at < now))  # tidy up old ones
    db.add(UserSession(id=sid, user_id=user.id, expires_at=expires))
    db.commit()
    token = jwt.encode({"sub": str(user.id), "sv": user.session_version or 0, "sid": sid, "exp": expires},
                       settings.secret_key, algorithm=_ALGORITHM)
    response.set_cookie(
        settings.session_cookie_name,
        token,
        max_age=settings.session_ttl_hours * 3600,
        httponly=True,
        secure=settings.cookie_secure,
        samesite="lax",
        path="/",
    )


def _session_claims(request: Request) -> dict | None:
    settings = get_settings()
    token = request.cookies.get(settings.session_cookie_name)
    if not token:
        return None
    try:
        payload = jwt.decode(token, settings.secret_key, algorithms=[_ALGORITHM])
        payload["sub"] = int(payload["sub"])
    except (jwt.PyJWTError, KeyError, ValueError):
        return None
    return payload


def clear_session(request: Request, response: Response, db: Session) -> None:
    """Sign this browser out: revokes its session, so a copy of the cookie stops working too."""
    claims = _session_claims(request)
    if claims and claims.get("sid"):
        db.execute(delete(UserSession).where(UserSession.id == claims["sid"]))
        db.commit()
    response.delete_cookie(get_settings().session_cookie_name, path="/")


def signed_in_user(request: Request, db: Session = Depends(get_db)) -> User:
    """The person signed in. Use for their account, admin rights and who-can-see-what settings."""
    unauthorized = HTTPException(status.HTTP_401_UNAUTHORIZED, "Not signed in")
    claims = _session_claims(request)
    if claims is None:
        raise unauthorized
    user = db.get(User, claims["sub"])
    if user is None or not user.is_active or claims.get("sv", 0) != (user.session_version or 0):
        raise unauthorized
    # Sessions issued before they were recorded carry no id; they run out within session_ttl_hours.
    if "sid" in claims:
        session = db.get(UserSession, claims["sid"])
        if session is None or session.user_id != user.id:
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
    """In-memory brute-force brake: too many failures for a key in a window → 429.

    Callers key it by address, and by address plus email, never by email alone: that would let anyone lock
    a person out of their account by failing to sign in as them."""

    MAX_KEYS = 10_000  # bounds memory however many addresses and emails are tried

    def __init__(self, limit: int = 10, window: timedelta = timedelta(minutes=15)):
        self.limit, self.window = limit, window
        self.failures: dict[str, list[datetime]] = {}

    def _recent(self, key: str) -> list[datetime]:
        cutoff = datetime.now(UTC) - self.window
        times = [t for t in self.failures.get(key, []) if t > cutoff]
        if times:
            self.failures[key] = times
        else:
            self.failures.pop(key, None)
        return times

    def _prune(self) -> None:
        for key in list(self.failures):
            self._recent(key)
        excess = len(self.failures) - self.MAX_KEYS
        if excess > 0:  # still too many: forget the keys whose last failure is oldest
            for key in sorted(self.failures, key=lambda k: self.failures[k][-1])[:excess]:
                del self.failures[key]

    def check(self, *keys: str, limit: int | None = None) -> None:
        if any(len(self._recent(k)) >= (limit or self.limit) for k in keys):
            raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, "Too many attempts; try again in 15 minutes")

    def fail(self, *keys: str) -> None:
        if len(self.failures) >= self.MAX_KEYS:
            self._prune()
        for k in keys:
            self.failures[k] = [*self._recent(k), datetime.now(UTC)]

    def clear(self, *keys: str) -> None:
        for k in keys:
            self.failures.pop(k, None)


login_throttle = LoginThrottle()
