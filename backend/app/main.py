from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import DEV_SECRET_KEY, get_settings
from app.routers import advisor, auth, conversions, foods, log, profile, recipes, sources


def create_app() -> FastAPI:
    settings = get_settings()
    if settings.secret_key == DEV_SECRET_KEY and not settings.database_url.startswith("sqlite"):
        raise RuntimeError("Set SECRET_KEY before running against a real database")
    app = FastAPI(title="Mealplan API", version="0.1.0")
    if settings.cors_origins:
        app.add_middleware(CORSMiddleware, allow_origins=settings.cors_origins, allow_credentials=True,
                           allow_methods=["*"], allow_headers=["*"])
    for module in (auth, profile, foods, sources, conversions, recipes, log, advisor):
        app.include_router(module.router)

    @app.get("/api/health")
    def health():
        return {"status": "ok"}

    return app


app = create_app()
