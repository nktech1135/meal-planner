# Mealplan

A web app for tracking meals and supplements, with an AI nutrition advisor.

- **Track** calories, macros, fiber, sugars, fats, cholesterol, 13 vitamins plus choline, 11
  minerals, water, caffeine and alcohol, plus non-nutrient supplement ingredients
  (botanicals, creatine, …).
- **Raw ↔ cooked conversions.** Log a raw ingredient by its cooked weight using a
  measured, published or derived cooking yield, with optional nutrient retention
  factors. Build recipes from raw ingredient weights and the finished dish weight.
- **Data you can trace.** Import from USDA FoodData Central and the NIH Dietary
  Supplement Label Database (free), or Nutritionix and Edamam (paid), or enter
  values by hand. Every value carries a trust level and citation. Crowdsourced
  data is off by default and always flagged `unverified`.
  See [docs/data-sources.md](docs/data-sources.md).
- **Targets.** DRI-based reference intakes and upper limits by sex and age, with
  per-user overrides. Supplement-only upper limits (e.g. magnesium) are checked
  against supplement intake.
- **AI advisor.** A Claude-powered chat that reads your profile, targets, logs and
  food database through read-only tools. It reviews your intake, flags upper-limit
  problems and suggests changes. It is told to cite data quality and to defer to
  clinicians on medical questions.
- **Multi-user.** Accounts with private foods, recipes, logs and conversations.
  Imported reference foods are shared. The first account created is the admin.

> Not medical advice. Reference values are for healthy, non-pregnant adults.

## Architecture

```
frontend/   React + TypeScript (Vite), served by nginx in production
backend/    FastAPI + SQLAlchemy 2 + Alembic; PostgreSQL in production, SQLite for dev/tests
  app/sources/    one adapter per data source (USDA FDC, NIH DSLD, Nutritionix, Edamam, Open Food Facts)
  app/services/   nutrient arithmetic, raw↔cooked conversion, targets (DRIs), daily summaries
  app/advisor/    Claude tool-use loop + read-only tools scoped to the signed-in user
docs/       data sources, trust levels, conversion method
```

nginx serves the SPA and proxies `/api/` to the API, so the browser sees a single
origin. Auth uses an httpOnly, SameSite=Lax session cookie (signed JWT); passwords
are hashed with Argon2.

## Development

Requirements: Python 3.12+, [uv](https://docs.astral.sh/uv/), Node 20+.

```bash
# API (http://localhost:8000, docs at /docs)
cd backend
uv sync
uv run alembic upgrade head          # creates ./mealplan.db (SQLite)
uv run uvicorn app.main:app --reload

# Web (http://localhost:5173, proxies /api to :8000)
cd frontend
npm install
npm run dev
```

Configuration is read from the environment or `backend/.env`. See
[.env.example](.env.example) for every setting. For the advisor, set
`ANTHROPIC_API_KEY`. For better USDA rate limits, set a free `USDA_FDC_API_KEY`.

Tests and lint:

```bash
cd backend && uv run pytest && uv run ruff check .
cd frontend && npm run build
```

Schema changes: edit `backend/app/models.py`, then
`uv run alembic revision --autogenerate -m "describe change"` and review the
generated file.

## Deployment (Docker Compose)

```bash
cp .env.example .env     # set POSTGRES_PASSWORD, SECRET_KEY, ANTHROPIC_API_KEY, …
docker compose up -d --build
# open http://<host>:8080, register the first (admin) account,
# then set ALLOW_REGISTRATION=false if sign-ups should be closed
```

Put it behind HTTPS (e.g. Caddy or a cloud load balancer terminating TLS in
front of the `web` container) and set `COOKIE_SECURE=true`. Back up the `pgdata`
volume. The API applies migrations on start-up.

## Status

| Area | State |
|---|---|
| Nutrient math, conversions, targets, API, auth, privacy | Covered by the backend test suite |
| USDA FDC and NIH DSLD adapters | Tested against recorded live responses (2026-10-30) |
| Nutritionix and Edamam adapters | Written to the vendors' published API docs; need a live check with real keys |
| AI advisor | Tool loop tested with a fake client; needs a live check with an API key |
| Docker images / Compose | Written, not yet built in this environment |
| Upper limits & reference intakes | Hand-transcribed from the DRI tables; verify before relying on them |
