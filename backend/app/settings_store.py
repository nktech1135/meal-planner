"""Application settings managed from the admin UI.

Values live in the ``app_settings`` table and override the environment, which is
only a bootstrap fallback. Secrets (API keys, passwords) are encrypted at rest with
a key derived from SECRET_KEY and are never sent back to the browser in full.
"""

import base64
import hashlib
import logging
from dataclasses import dataclass
from datetime import UTC, datetime

from cryptography.fernet import Fernet, InvalidToken
from fastapi import Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import Settings, get_settings
from app.db import get_db
from app.models import AppSetting

log = logging.getLogger(__name__)

ADVISOR_MODELS = ("claude-opus-5-5", "claude-sonnet-5-5", "claude-haiku-5-5", "claude-fable-5-1")
EFFORTS = ("low", "medium", "high", "xhigh", "max")


@dataclass(frozen=True)
class SettingDef:
    key: str  # same name as the Settings attribute it overrides
    label: str
    group: str
    kind: str  # secret | string | bool | int | choice
    description: str = ""
    choices: tuple[str, ...] = ()
    minimum: int | None = None
    maximum: int | None = None
    link: str | None = None


DEFS: tuple[SettingDef, ...] = (
    SettingDef("allow_registration", "Allow new sign-ups", "Accounts", "bool",
               "Anyone who can reach the site can create an account. Turn off once everyone has one."),
    SettingDef("public_url", "Site address", "Accounts", "string",
               "The address people use to reach this site, e.g. https://meals.example.com. Used in emailed links."),
    SettingDef("smtp_host", "SMTP server", "Email", "string", "Outgoing mail server for password-reset emails."),
    SettingDef("smtp_port", "SMTP port", "Email", "int", "Usually 587 (STARTTLS) or 465 (SSL).", minimum=1, maximum=65535),
    SettingDef("smtp_security", "Connection security", "Email", "choice", choices=("starttls", "ssl", "none")),
    SettingDef("smtp_username", "SMTP username", "Email", "string"),
    SettingDef("smtp_password", "SMTP password", "Email", "secret"),
    SettingDef("smtp_from", "From address", "Email", "string", "e.g. Mealplan <noreply@example.com>"),
    SettingDef("anthropic_api_key", "Anthropic API key", "AI advisor", "secret",
               "Enables the advisor.", link="https://console.anthropic.com/settings/keys"),
    SettingDef("advisor_model", "Model", "AI advisor", "choice", "Claude model used by the advisor.",
               choices=ADVISOR_MODELS),
    SettingDef("advisor_effort", "Effort", "AI advisor", "choice",
               "How hard the model thinks. Higher is slower and costs more.", choices=EFFORTS),
    SettingDef("advisor_daily_message_limit", "Messages per user per day", "AI advisor", "int",
               "Caps cost per user.", minimum=1, maximum=1000),
    SettingDef("advisor_web_research", "Look up authoritative sources", "AI advisor", "bool",
               "Lets the advisor search and read NIH, MedlinePlus, FDA, USDA and similar sites (e.g. supplement "
               "fact sheets and drug interactions) and cite them. Anthropic bills searches separately."),
    SettingDef("advisor_web_max_uses", "Source look-ups per reply", "AI advisor", "int",
               "Upper limit on searches and page reads for one reply.", minimum=1, maximum=10),
    SettingDef("usda_fdc_api_key", "USDA FoodData Central API key", "Data sources", "secret",
               "Free. Without one the shared DEMO_KEY is used, which is heavily rate-limited.",
               link="https://fdc.nal.usda.gov/api-key-signup"),
    SettingDef("nih_dsld_enabled", "NIH Dietary Supplement Label Database", "Data sources", "bool",
               "Free supplement label data."),
    SettingDef("nutritionix_app_id", "Nutritionix app ID", "Data sources", "secret",
               "Paid. Enables Nutritionix together with the key.", link="https://www.nutritionix.com/business/api"),
    SettingDef("nutritionix_app_key", "Nutritionix app key", "Data sources", "secret"),
    SettingDef("edamam_app_id", "Edamam app ID", "Data sources", "secret",
               "Paid tiers. Enables Edamam together with the key.", link="https://developer.edamam.com/food-database-api"),
    SettingDef("edamam_app_key", "Edamam app key", "Data sources", "secret"),
    SettingDef("enable_unverified_sources", "Allow crowdsourced data (Open Food Facts)", "Data sources", "bool",
               "Records can't be verified and are always flagged \"unverified\"."),
)
BY_KEY = {d.key: d for d in DEFS}


def _fernet() -> Fernet:
    digest = hashlib.sha256(b"mealplan-settings:" + get_settings().secret_key.encode()).digest()
    return Fernet(base64.urlsafe_b64encode(digest))


def encrypt(value: str) -> str:
    return _fernet().encrypt(value.encode()).decode()


def decrypt(token: str) -> str | None:
    try:
        return _fernet().decrypt(token.encode()).decode()
    except InvalidToken:
        log.warning("A stored secret could not be decrypted (SECRET_KEY changed?); treating it as unset")
        return None


def _stored(db: Session) -> dict[str, object]:
    out: dict[str, object] = {}
    for row in db.scalars(select(AppSetting)):
        d = BY_KEY.get(row.key)
        if d is None:
            continue
        out[row.key] = decrypt(row.value) if d.kind == "secret" and row.value is not None else row.value
    return out


def runtime_settings(db: Session) -> Settings:
    """Bootstrap settings with UI-managed values layered on top."""
    overrides = {k: v for k, v in _stored(db).items() if v is not None}
    return get_settings().model_copy(update=overrides)


def get_runtime(db: Session = Depends(get_db)) -> Settings:
    return runtime_settings(db)


def _mask(value: str | None) -> str | None:
    if not value:
        return None
    return "•" * 8 + value[-4:] if len(value) > 8 else "•" * 8


def describe(db: Session) -> list[dict]:
    """Every setting with its effective value (secrets masked) and where it comes from."""
    stored = _stored(db)
    base = get_settings()
    from_env = base.model_fields_set  # fields given by the environment or .env, not defaults
    rows = []
    for d in DEFS:
        in_db = stored.get(d.key) is not None
        value = stored[d.key] if in_db else getattr(base, d.key)
        if d.key == "usda_fdc_api_key" and value == "DEMO_KEY":
            value, in_db = None, False
        rows.append({
            "key": d.key, "label": d.label, "group": d.group, "kind": d.kind, "description": d.description,
            "choices": list(d.choices), "minimum": d.minimum, "maximum": d.maximum, "link": d.link,
            "value": _mask(value) if d.kind == "secret" else value,
            "is_set": bool(value) if d.kind == "secret" else True,
            "source": "settings" if in_db else ("environment" if d.key in from_env and value not in (None, "")
                                                else "default"),
        })
    return rows


def validate(key: str, value):
    d = BY_KEY.get(key)
    if d is None:
        raise ValueError(f"Unknown setting '{key}'")
    if value is None:
        return None
    if d.kind in ("secret", "string"):
        if not isinstance(value, str):
            raise ValueError(f"{d.label}: expected text")
        value = value.strip()
        if len(value) > 500 or "\n" in value or "\r" in value:
            raise ValueError(f"{d.label}: must be a single line")
        if d.kind == "secret" and any(c.isspace() for c in value):
            raise ValueError(f"{d.label}: must not contain spaces")
        return value or None
    if d.kind == "bool":
        if not isinstance(value, bool):
            raise ValueError(f"{d.label}: expected true or false")
        return value
    if d.kind == "int":
        if not isinstance(value, int) or isinstance(value, bool):
            raise ValueError(f"{d.label}: expected a whole number")
        if (d.minimum is not None and value < d.minimum) or (d.maximum is not None and value > d.maximum):
            raise ValueError(f"{d.label}: must be between {d.minimum} and {d.maximum}")
        return value
    if d.kind == "choice":
        if value not in d.choices:
            raise ValueError(f"{d.label}: must be one of {', '.join(d.choices)}")
        return value
    raise ValueError(f"Unsupported setting kind {d.kind}")


def update(db: Session, changes: dict, user_id: int) -> None:
    """Apply validated changes. ``None`` resets a setting to its environment/default value."""
    cleaned = {k: validate(k, v) for k, v in changes.items()}
    for key, value in cleaned.items():
        row = db.get(AppSetting, key)
        if value is None:
            if row is not None:
                db.delete(row)
            continue
        if row is None:
            row = AppSetting(key=key)
            db.add(row)
        row.value = encrypt(value) if BY_KEY[key].kind == "secret" else value
        row.updated_at = datetime.now(UTC)
        row.updated_by = user_id
    db.commit()
