import anthropic
import httpx
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.config import Settings
from app.db import get_db
from app.models import User
from app.security import admin_user
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
    }
