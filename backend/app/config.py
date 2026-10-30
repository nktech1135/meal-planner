from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

DEV_SECRET_KEY = "dev-only-insecure-secret-key-change-me"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # Core
    database_url: str = "sqlite:///./mealplan.db"
    secret_key: str = Field(default=DEV_SECRET_KEY, min_length=32)
    session_cookie_name: str = "mp_session"
    session_ttl_hours: int = 24 * 7
    cookie_secure: bool = False  # set true behind HTTPS in production
    allow_registration: bool = True
    cors_origins: list[str] = []
    static_dir: str | None = None  # built frontend (frontend/dist) to serve alongside the API

    # AI advisor (Claude)
    anthropic_api_key: str | None = None
    advisor_model: str = "claude-opus-5-5"
    advisor_effort: str = "medium"  # low | medium | high | xhigh | max
    advisor_daily_message_limit: int = 50
    advisor_max_tool_rounds: int = 8
    advisor_web_research: bool = True  # Claude web search/fetch, limited to authoritative health domains
    advisor_web_max_uses: int = 3

    # Data sources. Free, authoritative sources are on by default.
    usda_fdc_api_key: str = "DEMO_KEY"  # get a free key at https://fdc.nal.usda.gov/api-key-signup
    nih_dsld_enabled: bool = True
    # Paid / commercial sources: enabled only when credentials are present.
    nutritionix_app_id: str | None = None
    nutritionix_app_key: str | None = None
    edamam_app_id: str | None = None
    edamam_app_key: str | None = None
    # Crowdsourced data cannot be verified; it is off unless explicitly enabled,
    # and everything imported from it is flagged "unverified".
    enable_unverified_sources: bool = False

    http_timeout_seconds: float = 20.0
    user_agent: str = "mealplan/0.1 (+https://github.com/)"


@lru_cache
def get_settings() -> Settings:
    return Settings()
