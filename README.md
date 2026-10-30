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
frontend/   React + TypeScript (Vite); the built files are served by the API process
backend/    FastAPI + SQLAlchemy 2 + Alembic; PostgreSQL in production, SQLite for dev/tests
  app/sources/    one adapter per data source (USDA FDC, NIH DSLD, Nutritionix, Edamam, Open Food Facts)
  app/services/   nutrient arithmetic, raw↔cooked conversion, targets (DRIs), daily summaries
  app/advisor/    Claude tool-use loop + read-only tools scoped to the signed-in user
docs/       data sources, trust levels, conversion method
```

In production one uvicorn process serves both `/api/` and the built web app
(`STATIC_DIR`), so the browser sees a single origin. The app also sets the
security headers (CSP, frame denial, nosniff). Auth uses an httpOnly, SameSite=Lax session cookie (signed JWT); passwords
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

## Installing on a server

Supported: Debian 12+/Ubuntu 22.04+ with systemd, on x86_64 or arm64. No Docker.

```bash
# One line (once install.sh is published; see "Publishing" below):
curl -fsSL https://<your-host>/mealplan/raw/main/install.sh | sudo bash

# With HTTPS on your own domain (DNS must already point at this machine):
curl -fsSL https://<your-host>/mealplan/raw/main/install.sh | sudo bash -s -- install --domain meals.example.com

# Or from a checkout of this repository:
sudo ./install.sh install
```

The installer:
- installs PostgreSQL, git, curl and (with `--domain`) Caddy from apt;
- creates a `mealplan` system user and a PostgreSQL database it reaches over the
  local socket, so there's no database password to manage (`--db sqlite` is
  also available);
- installs pinned, checksum-verified copies of uv, Python 3.12 and Node.js
  under `/opt/mealplan/tools`, independent of the OS versions. Node is used only
  to build the web interface;
- builds the app into `/opt/mealplan/releases/<commit>`, runs migrations, and
  starts the `mealplan` systemd service with a hardened unit (read-only system,
  no capabilities);
- writes `/etc/mealplan/mealplan.env` with a generated `SECRET_KEY`. Add
  `ANTHROPIC_API_KEY` and a free `USDA_FDC_API_KEY` there, then run
  `sudo systemctl restart mealplan`.

Without `--domain` the app listens on port 8080 over plain HTTP; use that only
on a trusted network. Options: `--port`, `--listen`, `--db postgres|sqlite`,
`--repo`, `--branch`. Open the URL it prints and register. The first account is
the admin.

Day-to-day:

```bash
sudo mealplan status              # version, service state, URL, health
sudo mealplan upgrade             # latest commit on the tracked branch
sudo mealplan upgrade --ref v1.2  # a specific tag, branch or commit
sudo mealplan backup              # database backup into /var/lib/mealplan/backups
sudo mealplan uninstall           # remove the app; keep config, data and database
sudo mealplan uninstall --purge   # remove everything, including the database
journalctl -u mealplan -f         # logs
```

Upgrades build the new release while the current one keeps serving. They then
back up the database, stop the service, migrate, switch the `current` symlink
and start the new release. If migration or the health check fails, the upgrade
downgrades the schema, switches back to the previous release and tells you
where the backup is. The newest 10 backups are kept.

### Publishing

`install.sh` fetches the code with git. Push this repository somewhere the
server can reach, then set `DEFAULT_REPO` at the top of `install.sh` to its clone
URL. The one-line command then fetches `install.sh` from that repository's raw
file URL. For a private repository, use `--repo` with a URL that carries
credentials (e.g. a deploy token).

## Status

| Area | State |
|---|---|
| Nutrient math, conversions, targets, API, auth, privacy | Covered by the backend test suite |
| USDA FDC and NIH DSLD adapters | Run live end-to-end; tests use recorded responses (2026-10-30) |
| Web UI | Builds with no type errors; smoke-tested against the API through the dev proxy |
| Nutritionix and Edamam adapters | Written to the vendors' published API docs; need a live check with real keys |
| AI advisor | Tool loop tested with a fake client; needs a live check with an API key |
| Installer (`install.sh`) | Full install → upgrade → rollback → uninstall cycle tested in unprivileged test mode (SQLite, no systemd); the root-only steps (apt, PostgreSQL, systemd, Caddy) have not been run yet |
| Upper limits & reference intakes | Hand-transcribed from the DRI tables; verify before relying on them |
