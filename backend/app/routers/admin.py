import secrets

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.config import Settings
from app.db import get_db
from app.models import Food, ImportJob, LogEntry, Profile, RetentionProfile, User
from app.security import admin_user, hash_password
from app.services import datasets
from app.services.accounts import delete_user, end_sessions, is_last_admin, new_reset_token, reset_link
from app.services.mail import MailError, mail_configured, send_mail
from app.settings_store import describe, get_runtime, update
from app.sources.base import SourceError
from app.sources.registry import build_sources, http_client

router = APIRouter(prefix="/api", tags=["admin"])


class SettingsUpdate(BaseModel):
    values: dict[str, object]


@router.get("/admin/settings")
def read_settings(_: User = Depends(admin_user), db: Session = Depends(get_db)):
    return describe(db)


@router.put("/admin/settings")
def write_settings(body: SettingsUpdate, user: User = Depends(admin_user), db: Session = Depends(get_db)):
    try:
        update(db, body.values, user.id)
    except ValueError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc)) from None
    return describe(db)


@router.post("/admin/settings/test/{integration}")
def test_integration(integration: str, _: User = Depends(admin_user), settings: Settings = Depends(get_runtime)):
    """Check that the configured credentials work. Uses only free/cheap calls."""
    if integration == "anthropic":
        import anthropic

        if not settings.anthropic_api_key:
            return {"ok": False, "message": "No Anthropic API key set"}
        try:
            anthropic.Anthropic(api_key=settings.anthropic_api_key, max_retries=0, timeout=15).models.retrieve(
                settings.advisor_model)
        except anthropic.AuthenticationError:
            return {"ok": False, "message": "The key was rejected"}
        except anthropic.NotFoundError:
            return {"ok": False, "message": f"The key works, but model {settings.advisor_model} isn't available to it"}
        except anthropic.APIError as exc:
            return {"ok": False, "message": f"Anthropic API error: {exc.__class__.__name__}"}
        return {"ok": True, "message": f"Key works; {settings.advisor_model} is available"}

    sources = build_sources(settings, http_client())
    src = sources.get(integration)
    if src is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Unknown integration")
    if not src.enabled:
        return {"ok": False, "message": src.disabled_reason or "Not enabled"}
    try:
        hits = src.search("apple", 1)
    except (SourceError, httpx.HTTPError) as exc:
        return {"ok": False, "message": str(exc)}
    demo = " (using the shared DEMO_KEY)" if integration == "usda_fdc" and settings.usda_fdc_api_key == "DEMO_KEY" else ""
    return {"ok": True, "message": f"Connected{demo}; test search returned {len(hits)} result(s)"}


@router.get("/app-info")
def app_info(settings: Settings = Depends(get_runtime)):
    """Public, non-secret facts the UI needs (also before sign-in)."""
    return {
        "allow_registration": settings.allow_registration,
        "advisor_configured": bool(settings.anthropic_api_key),
        "usda_demo_key": settings.usda_fdc_api_key in ("", "DEMO_KEY"),
        "email_enabled": mail_configured(settings),
    }


# --- Reference datasets ---------------------------------------------------------------

def run_in_thread():
    """Job runner dependency (tests override it to run imports inline)."""
    return None


def _job_out(job: ImportJob | None) -> dict | None:
    if job is None:
        return None
    return {"id": job.id, "dataset": job.dataset, "release": job.release, "status": job.status, "progress": job.progress,
            "total": job.total, "message": job.message, "created_at": job.created_at, "finished_at": job.finished_at}


@router.get("/admin/datasets")
def list_datasets(_: User = Depends(admin_user), db: Session = Depends(get_db)):
    datasets.expire_stale_jobs(db)
    client = http_client()
    data_type = {"fdc_foundation": "Foundation", "fdc_sr_legacy": "SR Legacy", "fdc_survey": "Survey (FNDDS)",
                 "fdc_branded": "Branded"}
    out = []
    for ds in datasets.DATASETS:
        last = db.scalar(select(ImportJob).where(ImportJob.dataset == ds.key).order_by(ImportJob.id.desc()).limit(1))
        last_done = db.scalar(select(ImportJob).where(ImportJob.dataset == ds.key, ImportJob.status == "done")
                              .order_by(ImportJob.id.desc()).limit(1))
        if ds.root_key:
            available = datasets.release_of(datasets.latest_file(ds, client))
            count = db.scalar(select(func.count(Food.id)).where(Food.source == "usda_fdc",
                                                                Food.source_data_type == data_type[ds.key]))
        elif ds.source:
            available = ds.release
            count = db.scalar(select(func.count(Food.id)).where(Food.source == ds.source))
        else:
            available = ds.release
            count = db.scalar(select(func.count(RetentionProfile.code)))
        out.append({
            "key": ds.key, "label": ds.label, "description": ds.description, "size": ds.size,
            "country": ds.country, "licence": ds.licence, "licence_url": ds.licence_url, "attribution": ds.attribution,
            "available_release": available, "imported_release": last_done.release if last_done else None,
            "update_available": bool(last_done and last_done.release != available), "records": count,
            "last_job": _job_out(last),
        })
    return out


@router.post("/admin/datasets/{key}/import", status_code=202)
def import_dataset(key: str, user: User = Depends(admin_user), db: Session = Depends(get_db),
                   runner=Depends(run_in_thread)):
    if key not in datasets.BY_KEY:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Unknown dataset")
    running = datasets.active_job(db)
    if running:
        raise HTTPException(status.HTTP_409_CONFLICT, f"An import is already running ({running.dataset})")
    return _job_out(datasets.start_import(db, key, user.id, http_client(), runner))


@router.get("/admin/jobs/{job_id}")
def read_job(job_id: int, _: User = Depends(admin_user), db: Session = Depends(get_db)):
    datasets.expire_stale_jobs(db)
    job = db.get(ImportJob, job_id)
    if job is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Job not found")
    return _job_out(job)


@router.post("/admin/derive-yields")
def derive_yields(_: User = Depends(admin_user), db: Session = Depends(get_db)):
    return {"yields": datasets.derive_usda_yields(db)}



# --- Users ------------------------------------------------------------------------------

class UserAdminUpdate(BaseModel):
    is_admin: bool | None = None
    is_active: bool | None = None


class InviteIn(BaseModel):
    email: EmailStr
    display_name: str = ""
    # Set a password now instead of sending a link; pass it on to the person yourself.
    password: str | None = Field(default=None, min_length=10, max_length=200)
    is_admin: bool = False


def _user_row(db: Session, u: User) -> dict:
    return {"id": u.id, "email": u.email, "display_name": u.display_name, "is_admin": u.is_admin,
            "is_active": u.is_active, "created_at": u.created_at, "last_login_at": u.last_login_at,
            "log_entries": db.scalar(select(func.count(LogEntry.id)).where(LogEntry.user_id == u.id))}


def _target(db: Session, user_id: int) -> User:
    u = db.get(User, user_id)
    if u is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "User not found")
    return u


@router.get("/admin/users")
def list_users(_: User = Depends(admin_user), db: Session = Depends(get_db)):
    return [_user_row(db, u) for u in db.scalars(select(User).order_by(User.created_at))]


@router.post("/admin/users", status_code=201)
def invite_user(body: InviteIn, request: Request, admin: User = Depends(admin_user), db: Session = Depends(get_db),
                settings: Settings = Depends(get_runtime)):
    """Create an account (even with sign-ups closed): with a password set here, or with a link for the
    person to choose their own."""
    if db.scalar(select(User).where(User.email == body.email.lower())):
        raise HTTPException(status.HTTP_409_CONFLICT, "An account with that email already exists")
    user = User(email=body.email.lower(), display_name=body.display_name, is_admin=body.is_admin,
                # Without a password, a random one keeps the account unusable until they set their own.
                password_hash=hash_password(body.password or secrets.token_urlsafe(32)))
    user.profile = Profile()
    db.add(user)
    db.commit()
    if body.password:
        return {"user": _user_row(db, user), "link": None, "emailed": False}
    link = reset_link(settings, request, new_reset_token(db, user))
    emailed = False
    if mail_configured(settings):
        try:
            send_mail(settings, user.email, "You've been invited to Mealplan",
                      f"{admin.display_name or admin.email} created a Mealplan account for you.\n\n"
                      f"Open this link within 24 hours to choose your password:\n{link}")
            emailed = True
        except MailError:
            pass
    return {"user": _user_row(db, user), "link": link, "emailed": emailed}


@router.patch("/admin/users/{user_id}")
def update_user(user_id: int, body: UserAdminUpdate, admin: User = Depends(admin_user), db: Session = Depends(get_db)):
    u = _target(db, user_id)
    removing_admin = (body.is_admin is False and u.is_admin) or (body.is_active is False and u.is_admin)
    if removing_admin and is_last_admin(db, u):
        raise HTTPException(status.HTTP_409_CONFLICT, "There must be at least one active admin")
    if body.is_admin is not None:
        u.is_admin = body.is_admin
    if body.is_active is not None:
        if not body.is_active:
            end_sessions(u)  # signs them out everywhere
        u.is_active = body.is_active
    db.commit()
    return _user_row(db, u)


@router.post("/admin/users/{user_id}/reset-link")
def user_reset_link(user_id: int, request: Request, _: User = Depends(admin_user), db: Session = Depends(get_db),
                    settings: Settings = Depends(get_runtime)):
    """A one-time password reset link to pass on (works without email set up)."""
    u = _target(db, user_id)
    return {"link": reset_link(settings, request, new_reset_token(db, u)), "expires_in_hours": 24}


@router.post("/admin/users/{user_id}/sign-out")
def sign_out_everywhere(user_id: int, _: User = Depends(admin_user), db: Session = Depends(get_db)):
    end_sessions(_target(db, user_id))
    db.commit()
    return {"ok": True}


@router.delete("/admin/users/{user_id}", status_code=204)
def remove_user(user_id: int, admin: User = Depends(admin_user), db: Session = Depends(get_db)):
    u = _target(db, user_id)
    if u.id == admin.id:
        raise HTTPException(status.HTTP_409_CONFLICT, "Delete your own account from the Account page")
    delete_user(db, u)


@router.post("/admin/settings/test-email")
def test_email(admin: User = Depends(admin_user), settings: Settings = Depends(get_runtime)):
    try:
        send_mail(settings, admin.email, "Mealplan test email", "Email from Mealplan is working.")
    except MailError as exc:
        return {"ok": False, "message": str(exc)}
    return {"ok": True, "message": f"Sent a test email to {admin.email}"}
