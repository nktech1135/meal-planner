# Mealplan

A web app for tracking meals and supplements, with an AI nutrition advisor.

- **Track** calories, macros, fiber, sugars, fats, cholesterol, 13 vitamins plus choline, 11
  minerals, water, caffeine and alcohol, plus non-nutrient supplement ingredients
  (botanicals, creatine, …).
- **Fast logging.** Recent and frequent foods with their last amounts, saved
  meals, copy a meal or a whole day, and edit any entry.
- **Raw ↔ cooked conversions.** Log a raw ingredient by its cooked weight. About
  1,000 cooking yields are derived automatically from USDA raw/cooked pairs, and
  those use the analysed cooked entry's nutrients. You can also add measured or
  published yields with USDA nutrient-retention factors. Recipes are built from
  raw ingredient weights and the finished dish's weight.
- **Data you can trace.** A local copy of USDA's food databases (about 13,600
  foods, imported from Settings), the NIH Dietary Supplement Label Database,
  optional paid sources (Nutritionix, Edamam), or values entered by hand. Every
  value carries a trust level and citation. Crowdsourced data is off by default
  and always flagged `unverified`. Supplement label errors, such as an amount
  that contradicts the label's own %DV, are caught and flagged instead of
  counted. See [docs/data-sources.md](docs/data-sources.md).
- **Targets and trends.** DRI-based reference intakes and upper limits by sex and
  age, with overrides. Supplement-only upper limits (e.g. magnesium) are checked
  against supplement intake. 7/30/90-day averages show how often you hit each
  target. A weight log with a smoothed trend estimates your actual maintenance
  calories.
- **Meal planning.** Plan days ahead from foods, recipes and saved meals, see
  projected totals against targets, log a planned day in one click, and get a
  shopping list with recipes broken down into raw ingredients.
- **AI advisor.** A Claude-powered chat that reads your profile, targets, logs,
  trends, plan and food database. It reviews your intake and flags upper-limit
  problems. It can propose meal-plan items, which you approve before they're
  added. Optionally it looks up authoritative sources (NIH ODS, MedlinePlus,
  FDA, …) and cites them.
- **Multi-user, managed in the browser.** Accounts with private data; admin
  Settings for every API key and option (keys encrypted at rest); user
  management, invitations and password resets; data export and account
  deletion. The first account created is the admin.

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

Bootstrap configuration (database, `SECRET_KEY`) comes from the environment or
`backend/.env`; see [.env.example](.env.example). Everything else, including
API keys, is set in the app under **Settings** once you're signed in as the admin.

Tests and lint:

```bash
cd backend && uv run pytest && uv run ruff check .
cd frontend && npm run build
```

The backend tests use in-memory SQLite. To run them against PostgreSQL, point
`TEST_DATABASE_URL` at a scratch database, which is wiped for each test:
`TEST_DATABASE_URL=postgresql+psycopg://user@localhost/mealplan_test uv run pytest`.

Schema changes: edit `backend/app/models.py`, then
`uv run alembic revision --autogenerate -m "describe change"` and review the
generated file.

## Installing

Two ways, chosen by who runs the installer. Both work on x86_64 and arm64 Linux;
no Docker.

| | System-wide (`sudo`) | Per-user (no root) |
|---|---|---|
| Runs as | `mealplan` system user | you |
| Database | PostgreSQL (or `--db sqlite`) | SQLite |
| Service | systemd system unit | systemd user unit (`systemctl --user`) |
| HTTPS | `--domain` sets up Caddy | not built in; use localhost or an existing reverse proxy |
| Listens on | `0.0.0.0:8080` | `127.0.0.1:8080` |
| Distros | Debian 12+/Ubuntu 22.04+ | any systemd distro with git, curl, tar, xz |
| Files | `/opt/mealplan`, `/etc/mealplan`, `/var/lib/mealplan` | `~/.local/share/mealplan`, `~/.config/mealplan` |
| Command | `sudo mealplan …` | `mealplan …` (`~/.local/bin`) |

### Per-user install (no root)

```bash
curl -fsSL https://<your-host>/mealplan/raw/main/install.sh | bash
# or from a checkout:
./install.sh install
```

A user service normally stops when you log out and doesn't start at boot. The
installer turns on *lingering* (`loginctl enable-linger`) to keep it running.
Some systems only let an administrator do that. If so, the installer says so,
and `sudo loginctl enable-linger <you>` fixes it once. Pass `--no-linger` to
skip it. On machines without a systemd user manager (some containers), or with
`MEALPLAN_SERVICE=process`, the app runs as a background process instead and
won't come back after a reboot.

### System-wide install

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
- writes a small bootstrap file, `/etc/mealplan/mealplan.env` (per-user:
  `~/.config/mealplan/mealplan.env`), with the database location and a
  generated `SECRET_KEY`. The key also encrypts the API keys stored in
  Settings, so don't change it.

After installing, everything is done in the browser. Register (the first
account is the admin), then open **Settings**:
- add an Anthropic API key and a free USDA key;
- under **Data**, import the USDA databases;
- set up email if you want password-reset emails;
- close sign-ups, or invite people from **Users**.

Without `--domain` the app listens on port 8080 over plain HTTP; use that only
on a trusted network. Options: `--port`, `--listen`, `--db postgres|sqlite`,
`--repo`, `--branch`. Open the URL it prints and register. The first account is
the admin.

Day-to-day (drop `sudo` for a per-user install):

```bash
sudo mealplan status              # version, service state, URL, health
sudo mealplan restart             # after editing the configuration
sudo mealplan upgrade             # latest commit on the tracked branch
sudo mealplan upgrade --ref v1.2  # a specific tag, branch or commit
sudo mealplan backup              # database backup into /var/lib/mealplan/backups
sudo mealplan uninstall           # remove the app; keep config, data and database
sudo mealplan uninstall --purge   # remove everything, including the database
journalctl -u mealplan -f         # logs (per-user: journalctl --user -u mealplan -f)
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
| Installer (`install.sh`) | Tested in unprivileged test mode (SQLite, no root): install (from a file and piped), upgrade, rollback after a failed migration and after a failed start (schema downgraded), uninstall, reinstall reusing data, purge. The generated systemd unit passes `systemd-analyze verify`. Per-user mode run for real without root (in a scratch home, as a background process): install, restart, upgrade, uninstall, purge; its systemd user unit passes `systemd-analyze --user verify` but hasn't been started. Not yet run as root: apt packages, the system user, PostgreSQL setup, starting under systemd, Caddy |
| Upper limits & reference intakes | Hand-transcribed from the DRI tables; verify before relying on them |
