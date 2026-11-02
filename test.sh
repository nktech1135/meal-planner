#!/usr/bin/env bash
# Run every check locally: lint, backend tests (SQLite and PostgreSQL), migrations, the installer lint,
# the frontend type-check and build, and the browser tests. There is no CI; run this before pushing.
#
#   ./test.sh                     everything
#   ./test.sh backend frontend    only these stages
#   ./test.sh --skip e2e          everything but these stages
#
# Stages: backend, postgres, installer, frontend, e2e. A stage whose tools are missing fails and says
# how to install them, so a green run means everything ran.
set -uo pipefail

ROOT="$(cd "$(dirname "$0")" && pwd)"
ALL=(backend postgres installer frontend e2e)
if [[ -t 1 ]]; then BOLD=$'\e[1m' RED=$'\e[31m' GREEN=$'\e[32m' OFF=$'\e[0m'; else BOLD="" RED="" GREEN="" OFF=""; fi

usage() { sed -n '2,10p' "$0" | sed 's/^# \{0,1\}//'; exit 0; }

selected=() skip=()
while [[ $# -gt 0 ]]; do
  case "$1" in
    -h|--help) usage ;;
    --skip) IFS=, read -ra more <<<"${2:?--skip needs stage names}"; skip+=("${more[@]}"); shift 2 ;;
    *) selected+=("$1"); shift ;;
  esac
done
[[ ${#selected[@]} -gt 0 ]] || selected=("${ALL[@]}")
for s in "${selected[@]}" "${skip[@]}"; do
  [[ " ${ALL[*]} " == *" $s "* ]] || { echo "unknown stage: $s (stages: ${ALL[*]})" >&2; exit 2; }
done

step() { echo; echo "${BOLD}==> $*${OFF}"; }
need() {  # need COMMAND HOW-TO-INSTALL
  command -v "$1" >/dev/null 2>&1 && return 0
  echo "${RED}missing: $1${OFF}. Install it with: $2" >&2
  return 1
}

stage_backend() {
  need uv "curl -LsSf https://astral.sh/uv/install.sh | sh" || return 1
  cd "$ROOT/backend" || return 1
  step "backend: dependencies" && uv sync --frozen --quiet || return 1
  step "backend: lint" && uv run ruff check . || return 1
  step "backend: tests (SQLite)" && uv run pytest -q
}

# A throwaway PostgreSQL cluster in a temporary directory, on a private Unix socket: nothing to set up
# and no system service involved. Set TEST_DATABASE_URL to use an existing (scratch!) database instead.
stage_postgres() {
  need uv "curl -LsSf https://astral.sh/uv/install.sh | sh" || return 1
  cd "$ROOT/backend" || return 1
  local url="${TEST_DATABASE_URL:-}" dir="" rc=0 bin
  if [[ -z "$url" ]]; then
    bin="$(find /usr/lib/postgresql -mindepth 2 -maxdepth 2 -name bin -type d 2>/dev/null | sort -V | tail -n 1)"
    [[ -x "$bin/initdb" ]] || { need initdb "sudo apt-get install postgresql (then, if you don't want the system service: sudo systemctl disable --now postgresql)"; return 1; }
    dir="$(mktemp -d)"
    step "postgres: starting a temporary cluster"
    "$bin/initdb" -D "$dir/data" -U postgres -A trust --no-sync >"$dir/initdb.log" 2>&1 || { cat "$dir/initdb.log"; rm -rf "$dir"; return 1; }
    "$bin/pg_ctl" -D "$dir/data" -l "$dir/server.log" -w \
      -o "-k $dir -c listen_addresses='' -c fsync=off -c full_page_writes=off" start >/dev/null || { cat "$dir/server.log"; rm -rf "$dir"; return 1; }
    "$bin/createdb" -h "$dir" -U postgres mealplan_test || rc=1
    url="postgresql+psycopg://postgres@/mealplan_test?host=$dir"
  fi
  if ((rc == 0)); then
    uv sync --frozen --quiet || rc=1
    step "postgres: tests" && { TEST_DATABASE_URL="$url" uv run pytest -q || rc=1; }
    step "postgres: migrations up, check, down"
    DATABASE_URL="$url" SECRET_KEY="test-only-secret-key-0123456789-abcdefghijkl" bash -c '
      uv run python -c "from app.db import Base, engine; import app.models; Base.metadata.drop_all(engine)" &&
      uv run alembic upgrade head && uv run alembic check && uv run alembic downgrade base' || rc=1
  fi
  if [[ -n "$dir" ]]; then
    "$bin/pg_ctl" -D "$dir/data" -m fast stop >/dev/null 2>&1
    rm -rf "$dir"
  fi
  return "$rc"
}

stage_installer() {
  need shellcheck "sudo apt-get install shellcheck" || return 1
  step "installer: shellcheck" && shellcheck -S style "$ROOT/install.sh" "$ROOT/test.sh" "$ROOT/e2e/serve.sh"
}

stage_frontend() {
  need npm "a Node.js 20+ install (https://nodejs.org)" || return 1
  cd "$ROOT/frontend" || return 1
  step "frontend: packages" && npm ci --no-audit --no-fund --loglevel=error || return 1
  step "frontend: type-check and build" && npm run --silent build
}

stage_e2e() {
  need npm "a Node.js 20+ install (https://nodejs.org)" || return 1
  need uv "curl -LsSf https://astral.sh/uv/install.sh | sh" || return 1
  [[ -f "$ROOT/frontend/dist/index.html" ]] || { (cd "$ROOT/frontend" && npm ci --no-audit --no-fund --loglevel=error && node build.mjs) || return 1; }
  (cd "$ROOT/backend" && uv sync --frozen --quiet) || return 1
  cd "$ROOT/e2e" || return 1
  step "e2e: packages and browser" && npm ci --no-audit --no-fund --loglevel=error && npx playwright install chromium || return 1
  if ! node -e '
      const { chromium } = require("@playwright/test");
      chromium.launch().then((b) => b.close()).catch((e) => { console.error(e.message.split("\n").slice(0, 3).join("\n")); process.exit(1); });'; then
    echo "${RED}Chromium can't start: its system libraries are missing.${OFF} Install them once with: (cd \"$ROOT/e2e\" && sudo env \"PATH=\$PATH\" npx playwright install-deps chromium)" >&2
    return 1
  fi
  step "e2e: browser tests" && npx playwright test
}

failed=() passed=() skipped=()
for s in "${selected[@]}"; do
  if [[ " ${skip[*]} " == *" $s "* ]]; then skipped+=("$s"); continue; fi
  if ("stage_$s"); then passed+=("$s"); else failed+=("$s"); fi
done

echo
[[ ${#passed[@]} -gt 0 ]] && echo "${GREEN}passed:${OFF}  ${passed[*]}"
[[ ${#skipped[@]} -gt 0 ]] && echo "skipped: ${skipped[*]}"
if [[ ${#failed[@]} -gt 0 ]]; then echo "${RED}failed:  ${failed[*]}${OFF}"; exit 1; fi
echo "${GREEN}${BOLD}all selected checks passed${OFF}"
