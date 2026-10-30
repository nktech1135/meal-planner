#!/usr/bin/env bash
# Serve the built app on a throwaway SQLite database for end-to-end tests.
set -euo pipefail
here="$(cd "$(dirname "$0")" && pwd)"
root="$(dirname "$here")"
dir="$(mktemp -d)"
trap 'rm -rf "$dir"' EXIT
export DATABASE_URL="sqlite:///$dir/e2e.db"
export SECRET_KEY="e2e-only-secret-key-not-for-production-0123456789"
export STATIC_DIR="$root/frontend/dist"
cd "$root/backend"
uv run alembic upgrade head >/dev/null
uv run uvicorn app.main:app --host 127.0.0.1 --port "${E2E_PORT:-8799}"
