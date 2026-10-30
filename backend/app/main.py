from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse

from app.config import DEV_SECRET_KEY, get_settings
from app.routers import advisor, auth, conversions, foods, log, profile, recipes, sources

CSP = ("default-src 'self'; img-src 'self' data:; style-src 'self'; script-src 'self'; connect-src 'self'; "
       "frame-ancestors 'none'; base-uri 'self'; form-action 'self'")
SECURITY_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "strict-origin-when-cross-origin",
    "Permissions-Policy": "camera=(), microphone=(), geolocation=()",
}


def mount_frontend(app: FastAPI, dist: Path) -> None:
    """Serve the built single-page app: hashed assets, then index.html for every other non-API path."""
    root = dist.resolve()
    index = root / "index.html"
    if not index.is_file():
        raise RuntimeError(f"STATIC_DIR {dist} has no index.html; build the frontend first")

    @app.get("/{path:path}", include_in_schema=False)
    def spa(path: str):
        if path == "api" or path.startswith("api/"):
            raise HTTPException(404, "Not Found")
        candidate = (root / path).resolve()
        if path and candidate.is_file() and candidate.is_relative_to(root):
            immutable = candidate.parent == root / "assets"
            return FileResponse(candidate, headers={
                "Cache-Control": "public, max-age=31536000, immutable" if immutable else "no-cache"})
        return FileResponse(index, headers={"Cache-Control": "no-cache"})


def create_app() -> FastAPI:
    settings = get_settings()
    if settings.secret_key == DEV_SECRET_KEY and not settings.database_url.startswith("sqlite"):
        raise RuntimeError("Set SECRET_KEY before running against a real database")
    app = FastAPI(title="Mealplan API", version="0.1.0")
    if settings.cors_origins:
        app.add_middleware(CORSMiddleware, allow_origins=settings.cors_origins, allow_credentials=True,
                           allow_methods=["*"], allow_headers=["*"])

    @app.middleware("http")
    async def security_headers(request: Request, call_next):
        response = await call_next(request)
        for name, value in SECURITY_HEADERS.items():
            response.headers.setdefault(name, value)
        if request.url.path not in ("/docs", "/redoc"):  # the API docs pages load their UI from a CDN
            response.headers.setdefault("Content-Security-Policy", CSP)
        return response

    for module in (auth, profile, foods, sources, conversions, recipes, log, advisor):
        app.include_router(module.router)

    @app.get("/api/health")
    def health():
        return {"status": "ok"}

    if settings.static_dir:
        mount_frontend(app, Path(settings.static_dir))  # last: its catch-all route must not shadow the API
    return app


app = create_app()
