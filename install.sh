#!/usr/bin/env bash
# Mealplan installer, upgrader and uninstaller for Debian/Ubuntu (systemd).
#
#   Install:    curl -fsSL https://<host>/<path>/install.sh | sudo bash
#               curl -fsSL https://<host>/<path>/install.sh | sudo bash -s -- install --domain meals.example.com
#   From a checkout:  sudo ./install.sh install
#   Upgrade:    sudo mealplan upgrade [--ref <branch|tag|commit>]
#   Uninstall:  sudo mealplan uninstall [--purge]
#   Other:      sudo mealplan status | backup | help
#
# Layout:
#   /opt/mealplan/             code and toolchain (releases/<rev>, current -> releases/<rev>, tools/, repo.git)
#   /etc/mealplan/mealplan.env configuration (kept on upgrade and plain uninstall)
#   /var/lib/mealplan/         data: SQLite database (if used) and backups/
#   mealplan.service           systemd unit, runs as the "mealplan" system user
#
# Everything runs inside functions and main() is called on the last line, so a
# partially downloaded script does nothing.

set -Eeuo pipefail
umask 022

# --- Pinned settings -----------------------------------------------------------
# Set DEFAULT_REPO to where the code is published so the one-line install works.
DEFAULT_REPO="https://github.com/CHANGE-ME/mealplan.git"
DEFAULT_BRANCH="main"
DEFAULT_PORT=8080

UV_VERSION="0.11.25"
UV_SHA256_x86_64="1db18b5e76fa645a7f3865773139bdec8e2d46adbdbb35e7410b34fa8015ccd2"
UV_SHA256_aarch64="e0e9d73f74e06a7dcd53910d5962146ab48f0af9c92cc8df33a37baa0121014d"
NODE_VERSION="24.22.2"
NODE_SHA256_x64="48cc0e21e048790e54c0cf5749c2725005313d652651c40b7a21feb9697aaf75"
NODE_SHA256_arm64="eb187837a2230d4047161ac0be008584e16b46f726e9c9490ee35dc6b17d9ba8"
KEEP_BACKUPS=10

# --- Paths ---------------------------------------------------------------------
# MEALPLAN_TEST_ROOT relocates every path under one directory and skips everything
# that needs root (apt, users, systemd, PostgreSQL, Caddy). For development only.
TEST_ROOT="${MEALPLAN_TEST_ROOT:-}"
SERVICE_USER="mealplan"
PREFIX="$TEST_ROOT/opt/mealplan"
ETC_DIR="$TEST_ROOT/etc/mealplan"
VAR_DIR="$TEST_ROOT/var/lib/mealplan"
BIN_PATH="$TEST_ROOT/usr/local/sbin/mealplan"
UNIT_PATH="$TEST_ROOT/etc/systemd/system/mealplan.service"
CADDYFILE="$TEST_ROOT/etc/caddy/Caddyfile"
CADDY_SITE="$TEST_ROOT/etc/caddy/mealplan.caddy"
ENV_FILE="$ETC_DIR/mealplan.env"
STATE_FILE="$ETC_DIR/install.conf"
BACKUP_DIR="$VAR_DIR/backups"
TOOLS="$PREFIX/tools"
CACHE="$PREFIX/cache"
REPO_DIR="$PREFIX/repo.git"
RELEASES="$PREFIX/releases"
CURRENT="$PREFIX/current"
PREVIOUS="$PREFIX/previous"
UV="$TOOLS/uv/uv"

# --- Output helpers --------------------------------------------------------------
if [[ -t 2 ]]; then C_OK=$'\033[1;32m' C_WARN=$'\033[1;33m' C_ERR=$'\033[1;31m' C_OFF=$'\033[0m'
else C_OK="" C_WARN="" C_ERR="" C_OFF=""; fi
log()  { printf '%s==>%s %s\n' "$C_OK" "$C_OFF" "$*" >&2; }
warn() { printf '%swarning:%s %s\n' "$C_WARN" "$C_OFF" "$*" >&2; }
die()  { printf '%serror:%s %s\n' "$C_ERR" "$C_OFF" "$*" >&2; exit 1; }
on_err() { printf '%serror:%s command failed (line %s): %s\n' "$C_ERR" "$C_OFF" "$1" "$2" >&2; }
trap 'on_err "$LINENO" "$BASH_COMMAND"' ERR

test_mode() { [[ -n "$TEST_ROOT" ]]; }
git_() { git -c safe.directory='*' "$@"; }

usage() {
  cat <<'EOF'
Usage: mealplan <command> [options]

Commands:
  install     Install Mealplan (default when no command is given)
                --domain NAME    serve over HTTPS at NAME via Caddy (DNS must point here)
                --port N         local port for the app (default 8080)
                --listen ADDR    bind address when no domain is used (default 0.0.0.0)
                --db postgres|sqlite   database (default postgres)
                --repo URL|PATH  git repository to install from
                --branch NAME    branch to track (default main)
  upgrade     Upgrade to the latest commit of the tracked branch
                --ref REF        a specific branch, tag or commit instead
                --force          rebuild even if already at that commit
  uninstall   Remove the app; keeps config, data and the database
                --purge          also delete config, data, backups, database and the service user
                --yes            don't ask for confirmation
  status      Show installed version, service state and URL
  backup      Back up the database now (to /var/lib/mealplan/backups)
  help        Show this help
EOF
}

# --- Checks ----------------------------------------------------------------------
require_root() {
  test_mode && return 0
  [[ $EUID -eq 0 ]] || die "run as root, e.g. with sudo"
}

require_platform() {
  test_mode && return 0
  [[ -r /etc/os-release ]] || die "cannot identify this Linux distribution"
  # shellcheck disable=SC1091
  . /etc/os-release
  [[ " ${ID:-} ${ID_LIKE:-} " == *" debian "* || "${ID:-}" == "debian" || "${ID:-}" == "ubuntu" ]] \
    || die "only Debian and Ubuntu are supported (found ${PRETTY_NAME:-unknown})"
  [[ -d /run/systemd/system ]] || die "systemd is required"
}

detect_arch() {
  case "$(uname -m)" in
    x86_64)        UV_ARCH="x86_64";  UV_SHA="$UV_SHA256_x86_64";  NODE_ARCH="x64";   NODE_SHA="$NODE_SHA256_x64" ;;
    aarch64|arm64) UV_ARCH="aarch64"; UV_SHA="$UV_SHA256_aarch64"; NODE_ARCH="arm64"; NODE_SHA="$NODE_SHA256_arm64" ;;
    *) die "unsupported CPU architecture: $(uname -m)" ;;
  esac
}

take_lock() {
  local lock="$TEST_ROOT/run/lock/mealplan.lock"
  mkdir -p "$(dirname "$lock")"
  exec 9>"$lock"
  flock -n 9 || die "another mealplan install/upgrade is already running"
}

confirm() {
  local prompt="$1" reply
  [[ "${ASSUME_YES:-0}" == 1 ]] && return 0
  { : </dev/tty; } 2>/dev/null || die "cannot ask for confirmation without a terminal; re-run with --yes"
  read -r -p "$prompt [y/N] " reply </dev/tty
  [[ "$reply" == [yY] || "$reply" == [yY][eE][sS] ]]
}

# --- State -----------------------------------------------------------------------
save_state() {
  {
    printf '# Written by the mealplan installer. Do not edit.\n'
    printf 'REPO=%q\nBRANCH=%q\nDB_KIND=%q\nDOMAIN=%q\nCADDY_MANAGED=%q\n' \
      "$REPO" "$BRANCH" "$DB_KIND" "$DOMAIN" "$CADDY_MANAGED"
  } >"$STATE_FILE"
}

load_state() {
  [[ -f "$STATE_FILE" ]] || die "Mealplan is not installed (no $STATE_FILE)"
  # shellcheck disable=SC1090
  . "$STATE_FILE"
}

env_value() {  # env_value KEY -> value from the config file
  sed -n "s/^$1=//p" "$ENV_FILE" | tail -n1
}

# --- System setup ----------------------------------------------------------------
install_packages() {
  test_mode && return 0
  local pkgs=(ca-certificates curl git tar xz-utils util-linux)
  [[ "$DB_KIND" == postgres ]] && pkgs+=(postgresql)
  [[ -n "$DOMAIN" ]] && pkgs+=(caddy)
  log "Installing system packages: ${pkgs[*]}"
  export DEBIAN_FRONTEND=noninteractive
  apt-get update -qq
  apt-get install -y -qq --no-install-recommends "${pkgs[@]}" >/dev/null
}

ensure_user() {
  test_mode && return 0
  if ! id -u "$SERVICE_USER" >/dev/null 2>&1; then
    log "Creating system user $SERVICE_USER"
    useradd --system --user-group --home-dir "$VAR_DIR" --no-create-home --shell /usr/sbin/nologin "$SERVICE_USER"
  fi
}

make_dirs() {
  mkdir -p "$PREFIX" "$TOOLS" "$CACHE" "$RELEASES" "$(dirname "$BIN_PATH")"
  if test_mode; then
    mkdir -p "$ETC_DIR" "$BACKUP_DIR"
  else
    install -d -m 0750 -o root -g "$SERVICE_USER" "$ETC_DIR"
    install -d -m 0750 -o "$SERVICE_USER" -g "$SERVICE_USER" "$VAR_DIR" "$BACKUP_DIR"
  fi
}

as_service() {  # run a command as the service user, with the app's configuration loaded
  local script="set -a; . '$ENV_FILE'; set +a; $*"
  if test_mode; then bash -c "$script"
  else runuser -u "$SERVICE_USER" -- bash -c "$script"; fi
}

# --- Toolchain (pinned and checksum-verified) ------------------------------------
fetch_verified() {  # fetch_verified URL SHA256 DEST
  curl -fsSL --retry 3 --proto '=https' -o "$3" "$1" || die "download failed: $1"
  echo "$2  $3" | sha256sum -c --quiet - || die "checksum mismatch for $1"
}

install_uv() {
  if [[ -x "$UV" ]] && [[ "$("$UV" --version 2>/dev/null)" == "uv $UV_VERSION"* ]]; then return 0; fi
  log "Installing uv $UV_VERSION"
  local name="uv-$UV_ARCH-unknown-linux-gnu" tmp
  tmp="$(mktemp -d)"
  fetch_verified "https://github.com/astral-sh/uv/releases/download/$UV_VERSION/$name.tar.gz" "$UV_SHA" "$tmp/uv.tgz"
  tar -xzf "$tmp/uv.tgz" -C "$tmp"
  rm -rf "$TOOLS/uv" && mkdir -p "$TOOLS/uv"
  install -m 0755 "$tmp/$name/uv" "$TOOLS/uv/uv"
  rm -rf "$tmp"
}

install_node() {
  local node="$TOOLS/node/bin/node"
  if [[ -x "$node" ]] && [[ "$("$node" --version 2>/dev/null)" == "v$NODE_VERSION" ]]; then return 0; fi
  log "Installing Node.js $NODE_VERSION (used only to build the web interface)"
  local name="node-v$NODE_VERSION-linux-$NODE_ARCH" tmp
  tmp="$(mktemp -d)"
  fetch_verified "https://nodejs.org/dist/v$NODE_VERSION/$name.tar.xz" "$NODE_SHA" "$tmp/node.txz"
  tar -xJf "$tmp/node.txz" -C "$tmp"
  rm -rf "$TOOLS/node" && mv "$tmp/$name" "$TOOLS/node"
  rm -rf "$tmp"
}

# --- Source and releases -----------------------------------------------------------
default_repo() {
  # Run as a file from inside a checkout: install from it. (Piped through bash, there's no file.)
  local src="${BASH_SOURCE[0]:-}" here=""
  [[ -f "$src" ]] && here="$(cd "$(dirname "$src")" && pwd)"
  if [[ -n "$here" && -d "$here/.git" && -d "$here/backend" && -d "$here/frontend" ]]; then
    echo "$here"
  else
    echo "$DEFAULT_REPO"
  fi
}

fetch_source() {
  if [[ ! -d "$REPO_DIR" ]]; then
    [[ "$REPO" == *CHANGE-ME* ]] && die "no repository configured: pass --repo <git URL or path>, or set DEFAULT_REPO in install.sh"
    log "Fetching source from $REPO"
    git_ clone --quiet --bare "$REPO" "$REPO_DIR"
  fi
  git_ -C "$REPO_DIR" fetch --quiet --prune --tags origin '+refs/heads/*:refs/heads/*'
}

resolve_ref() {  # resolve_ref REF -> full commit id
  git_ -C "$REPO_DIR" rev-parse --verify --quiet "$1^{commit}" || die "unknown branch, tag or commit: $1"
}

build_release() {  # build_release REV -> path of the built release
  local rev="$1" rel="$RELEASES/${1:0:12}"
  rm -rf "$rel" && mkdir -p "$rel"
  log "Unpacking ${rev:0:12}"
  git_ -C "$REPO_DIR" archive "$rev" | tar -x -C "$rel"
  printf '%s\n' "$rev" >"$rel/REVISION"

  log "Installing Python dependencies"
  (
    cd "$rel/backend"
    UV_PROJECT_ENVIRONMENT="$rel/venv" UV_PYTHON_INSTALL_DIR="$TOOLS/python" UV_CACHE_DIR="$CACHE/uv" \
      UV_PYTHON_PREFERENCE=only-managed UV_COMPILE_BYTECODE=1 UV_NO_PROGRESS=1 "$UV" sync --quiet --frozen --no-dev
    # The service's filesystem is read-only, so compile the app's bytecode now.
    "$rel/venv/bin/python" -m compileall -q app alembic >/dev/null
  ) >&2

  log "Building the web interface"
  (
    cd "$rel/frontend"
    export PATH="$TOOLS/node/bin:$PATH" npm_config_cache="$CACHE/npm" npm_config_update_notifier=false
    npm ci --ignore-scripts --no-audit --no-fund --loglevel=error >/dev/null
    npm run --silent build >/dev/null
    rm -rf node_modules
  ) >&2
  [[ -f "$rel/frontend/dist/index.html" ]] || die "web interface build produced no index.html"
  echo "$rel"
}

current_release() { if [[ -L "$CURRENT" ]]; then readlink -f "$CURRENT"; fi; }

switch_to() {  # switch_to RELEASE_DIR
  local old
  old="$(current_release)"
  if [[ -n "$old" && "$old" != "$1" ]]; then ln -sfn "$old" "$PREVIOUS"; fi
  ln -sfn "$1" "$CURRENT"
}

prune_releases() {
  local keep_cur keep_prev dir
  keep_cur="$(current_release)"
  keep_prev=""
  if [[ -L "$PREVIOUS" ]]; then keep_prev="$(readlink -f "$PREVIOUS")"; fi
  for dir in "$RELEASES"/*; do
    [[ -d "$dir" && "$dir" != "$keep_cur" && "$dir" != "$keep_prev" ]] && rm -rf "$dir"
  done
  return 0
}

install_cli() {  # install_cli RELEASE_DIR
  install -m 0755 "$1/install.sh" "$BIN_PATH"
}

# --- Configuration -------------------------------------------------------------------
random_secret() { head -c 48 /dev/urandom | base64 -w0 | tr '+/' '-_' | tr -d '='; }

write_config() {
  if [[ -f "$ENV_FILE" ]]; then
    log "Keeping existing configuration $ENV_FILE"
    return 0
  fi
  local host="$LISTEN" secure=false db_url
  if [[ -n "$DOMAIN" ]]; then host=127.0.0.1; secure=true; fi
  if [[ "$DB_KIND" == postgres ]]; then
    db_url="postgresql+psycopg://$SERVICE_USER@/$SERVICE_USER?host=/var/run/postgresql"
  else
    db_url="sqlite:///$VAR_DIR/mealplan.db"
  fi
  log "Writing configuration $ENV_FILE"
  cat >"$ENV_FILE" <<EOF
# Mealplan configuration. After editing, apply with: sudo systemctl restart mealplan
# Values must not contain spaces or quotes.

MEALPLAN_HOST=$host
MEALPLAN_PORT=$PORT
DATABASE_URL=$db_url
SECRET_KEY=$(random_secret)
COOKIE_SECURE=$secure
# The first account to register becomes admin. Set false afterwards to close sign-ups.
ALLOW_REGISTRATION=true
STATIC_DIR=$CURRENT/frontend/dist

# AI advisor (Claude): https://console.anthropic.com/
ANTHROPIC_API_KEY=
ADVISOR_MODEL=claude-opus-5-5
ADVISOR_EFFORT=medium
ADVISOR_DAILY_MESSAGE_LIMIT=50

# Data sources. Free USDA key: https://fdc.nal.usda.gov/api-key-signup
USDA_FDC_API_KEY=DEMO_KEY
NIH_DSLD_ENABLED=true
NUTRITIONIX_APP_ID=
NUTRITIONIX_APP_KEY=
EDAMAM_APP_ID=
EDAMAM_APP_KEY=
# Crowdsourced (unverifiable) data; records are always flagged "unverified".
ENABLE_UNVERIFIED_SOURCES=false
EOF
  if test_mode; then chmod 0600 "$ENV_FILE"
  else chown root:"$SERVICE_USER" "$ENV_FILE" && chmod 0640 "$ENV_FILE"; fi
}

setup_postgres() {
  [[ "$DB_KIND" == postgres ]] || return 0
  test_mode && die "PostgreSQL is not available in test mode; use --db sqlite"
  systemctl enable --now postgresql >/dev/null 2>&1 || systemctl start postgresql
  local psql=(runuser -u postgres -- psql -v ON_ERROR_STOP=1 -qtA)
  if [[ "$("${psql[@]}" -c "SELECT 1 FROM pg_roles WHERE rolname='$SERVICE_USER'")" != 1 ]]; then
    log "Creating PostgreSQL role $SERVICE_USER (local socket authentication, no password)"
    runuser -u postgres -- createuser "$SERVICE_USER"
  fi
  if [[ "$("${psql[@]}" -c "SELECT 1 FROM pg_database WHERE datname='$SERVICE_USER'")" != 1 ]]; then
    log "Creating PostgreSQL database $SERVICE_USER"
    runuser -u postgres -- createdb -O "$SERVICE_USER" -E UTF8 "$SERVICE_USER"
  fi
}

setup_caddy() {
  [[ -n "$DOMAIN" ]] || return 0
  test_mode && return 0
  log "Configuring Caddy for https://$DOMAIN"
  cat >"$CADDY_SITE" <<EOF
# Managed by the mealplan installer.
$DOMAIN {
	encode gzip
	reverse_proxy 127.0.0.1:$PORT
}
EOF
  grep -qxF "import $CADDY_SITE" "$CADDYFILE" 2>/dev/null || printf '\nimport %s\n' "$CADDY_SITE" >>"$CADDYFILE"
  caddy validate --config "$CADDYFILE" --adapter caddyfile >/dev/null 2>&1 || die "Caddy rejected the configuration; check $CADDYFILE"
  systemctl enable caddy >/dev/null 2>&1
  systemctl reload caddy 2>/dev/null || systemctl restart caddy
  CADDY_MANAGED=1
}

remove_caddy_site() {
  [[ "${CADDY_MANAGED:-0}" == 1 ]] || return 0
  test_mode && return 0
  rm -f "$CADDY_SITE"
  if [[ -f "$CADDYFILE" ]]; then
    sed -i "\\|^import $CADDY_SITE\$|d" "$CADDYFILE"
    systemctl reload caddy 2>/dev/null || true
  fi
}

# --- Database operations -----------------------------------------------------------
alembic_() {  # alembic_ RELEASE_DIR ARGS...
  local rel="$1"; shift
  as_service "cd '$rel/backend' && exec '$rel/venv/bin/alembic' $*"
}

db_revision() {  # current schema revision (empty if none)
  alembic_ "$1" current 2>/dev/null | awk 'NF {print $1; exit}'
}

backup_db() {
  local ts out kind url
  ts="$(date +%Y%m%d-%H%M%S)"
  url="$(env_value DATABASE_URL)"
  if [[ "$url" == sqlite* ]]; then
    kind=sqlite
    local db="${url#sqlite:///}"
    [[ -f "$db" ]] || { echo ""; return 0; }
    out="$BACKUP_DIR/mealplan-$ts.sqlite3"
    as_service "'$(current_release)/venv/bin/python' -c 'import sqlite3,sys; s=sqlite3.connect(sys.argv[1]); d=sqlite3.connect(sys.argv[2]); s.backup(d); d.close()' '$db' '$out'" >&2
  else
    kind=postgres
    out="$BACKUP_DIR/mealplan-$ts.dump"
    as_service "pg_dump -Fc -f '$out' '$SERVICE_USER'" >&2
  fi
  # Keep the newest backups only.
  find "$BACKUP_DIR" -maxdepth 1 -name 'mealplan-*' -printf '%T@ %p\n' | sort -rn | tail -n +$((KEEP_BACKUPS + 1)) \
    | cut -d' ' -f2- | xargs -r rm -f
  log "Backed up the $kind database to $out"
  echo "$out"
}

# --- Service -------------------------------------------------------------------------
write_unit() {
  test_mode && return 0
  cat >"$UNIT_PATH" <<EOF
# Managed by the mealplan installer.
[Unit]
Description=Mealplan meal and supplement tracker
After=network-online.target postgresql.service
Wants=network-online.target

[Service]
Type=simple
User=$SERVICE_USER
Group=$SERVICE_USER
EnvironmentFile=$ENV_FILE
WorkingDirectory=$CURRENT/backend
ExecStart=$CURRENT/venv/bin/uvicorn app.main:app --host \${MEALPLAN_HOST} --port \${MEALPLAN_PORT} --proxy-headers --forwarded-allow-ips 127.0.0.1 --no-server-header
Restart=on-failure
RestartSec=3
UMask=0027
NoNewPrivileges=true
ProtectSystem=strict
ProtectHome=true
PrivateTmp=true
PrivateDevices=true
ReadWritePaths=$VAR_DIR
ProtectKernelTunables=true
ProtectKernelModules=true
ProtectControlGroups=true
RestrictSUIDSGID=true
RestrictRealtime=true
LockPersonality=true
CapabilityBoundingSet=

[Install]
WantedBy=multi-user.target
EOF
  systemctl daemon-reload
}

service_stop() {
  if test_mode; then
    local pidfile="$VAR_DIR/test-server.pid"
    if [[ -f "$pidfile" ]]; then kill "$(cat "$pidfile")" 2>/dev/null || true; rm -f "$pidfile"; sleep 1; fi
  else
    systemctl stop mealplan 2>/dev/null || true
  fi
}

service_start() {
  if test_mode; then
    # Launched directly (not via a function, which would fork a wrapper) so $! is the server's PID,
    # and without fd 9 so the server doesn't hold the installer lock.
    bash -c "set -a; . '$ENV_FILE'; set +a; cd '$CURRENT/backend' && exec '$CURRENT/venv/bin/uvicorn' app.main:app \
      --host \"\$MEALPLAN_HOST\" --port \"\$MEALPLAN_PORT\"" >"$VAR_DIR/test-server.log" 2>&1 9>&- &
    echo $! >"$VAR_DIR/test-server.pid"
  else
    systemctl enable mealplan >/dev/null 2>&1
    systemctl restart mealplan
  fi
}

health_check() {
  local port
  port="$(env_value MEALPLAN_PORT)"
  for _ in $(seq 1 40); do
    if curl -fsS -m 2 "http://127.0.0.1:$port/api/health" >/dev/null 2>&1 \
       && curl -fsS -m 2 "http://127.0.0.1:$port/" | grep -q '<div id="root">'; then
      return 0
    fi
    sleep 0.5
  done
  return 1
}

public_url() {
  if [[ -n "${DOMAIN:-}" ]]; then echo "https://$DOMAIN"; return; fi
  local host ip
  host="$(env_value MEALPLAN_HOST)"
  ip="$host"
  [[ "$host" == 0.0.0.0 ]] && ip="$(hostname -I 2>/dev/null | awk '{print $1}')"
  echo "http://${ip:-localhost}:$(env_value MEALPLAN_PORT)"
}

# --- Commands --------------------------------------------------------------------------
cmd_install() {
  REPO="" BRANCH="$DEFAULT_BRANCH" DOMAIN="" PORT="$DEFAULT_PORT" LISTEN="0.0.0.0" DB_KIND="postgres" CADDY_MANAGED=0
  while [[ $# -gt 0 ]]; do
    case "$1" in
      --repo) REPO="${2:?--repo needs a value}"; shift 2 ;;
      --branch) BRANCH="${2:?--branch needs a value}"; shift 2 ;;
      --domain) DOMAIN="${2:?--domain needs a value}"; shift 2 ;;
      --port) PORT="${2:?--port needs a value}"; shift 2 ;;
      --listen) LISTEN="${2:?--listen needs a value}"; shift 2 ;;
      --db) DB_KIND="${2:?--db needs a value}"; shift 2 ;;
      --yes|-y) ASSUME_YES=1; shift ;;
      *) die "unknown option for install: $1 (see: mealplan help)" ;;
    esac
  done
  if ! [[ "$PORT" =~ ^[0-9]+$ ]] || ((PORT < 1024 || PORT > 65535)); then die "--port must be 1024-65535"; fi
  [[ "$DB_KIND" == postgres || "$DB_KIND" == sqlite ]] || die "--db must be postgres or sqlite"
  [[ -z "$DOMAIN" || "$DOMAIN" =~ ^[A-Za-z0-9.-]+$ ]] || die "invalid --domain"
  [[ "$LISTEN" =~ ^[0-9A-Fa-f.:]+$ ]] || die "invalid --listen address"
  [[ -n "$REPO" ]] || REPO="$(default_repo)"
  if [[ -d "$REPO" ]]; then REPO="$(cd "$REPO" && pwd)"; fi

  require_root
  require_platform
  detect_arch
  if [[ -e "$CURRENT" ]]; then die "Mealplan is already installed; use: sudo mealplan upgrade"; fi
  if [[ -f "$STATE_FILE" ]]; then
    # Re-installing after a plain uninstall: keep using the same database.
    local keep_db
    keep_db="$(sed -n 's/^DB_KIND=//p' "$STATE_FILE")"
    if [[ -n "$keep_db" && "$keep_db" != "$DB_KIND" ]]; then
      warn "reusing the existing $keep_db database from the previous install"
      DB_KIND="$keep_db"
    fi
  fi

  take_lock
  install_packages
  ensure_user
  make_dirs
  install_uv
  install_node
  fetch_source
  local rev rel
  rev="$(resolve_ref "$BRANCH")"
  rel="$(build_release "$rev")"
  write_config
  PORT="$(env_value MEALPLAN_PORT)"  # a kept configuration from an earlier install wins
  setup_postgres
  switch_to "$rel"
  log "Applying database migrations"
  alembic_ "$CURRENT" upgrade head
  write_unit
  setup_caddy
  save_state
  install_cli "$rel"
  service_start
  health_check || die "the service did not come up; see: journalctl -u mealplan -n 50"

  log "Mealplan ${rev:0:12} is running at $(public_url)"
  cat >&2 <<EOF

  Next steps:
    1. Open $(public_url) and register. The first account becomes the admin.
    2. Add your keys to $ENV_FILE (ANTHROPIC_API_KEY for the advisor, a free
       USDA_FDC_API_KEY), then run: sudo systemctl restart mealplan
    3. Optionally set ALLOW_REGISTRATION=false once everyone has an account.

  Manage it with:  sudo mealplan status | upgrade | backup | uninstall
EOF
  if [[ -z "$DOMAIN" && "$(env_value MEALPLAN_HOST)" != 127.0.0.1 ]]; then
    warn "traffic is unencrypted HTTP. For use beyond a trusted network, reinstall with --domain to get HTTPS."
  fi
}

cmd_upgrade() {
  local ref="" force=0
  while [[ $# -gt 0 ]]; do
    case "$1" in
      --ref) ref="${2:?--ref needs a value}"; shift 2 ;;
      --force) force=1; shift ;;
      *) die "unknown option for upgrade: $1" ;;
    esac
  done
  require_root
  load_state
  detect_arch
  take_lock
  local old_rel old_rev new_rev
  old_rel="$(current_release)"
  [[ -n "$old_rel" ]] || die "no current release found under $PREFIX"
  old_rev="$(cat "$old_rel/REVISION")"
  install_uv
  install_node
  fetch_source
  new_rev="$(resolve_ref "${ref:-$BRANCH}")"
  if [[ "$new_rev" == "$old_rev" && "$force" != 1 ]]; then
    log "Already at ${old_rev:0:12}; nothing to do (use --force to rebuild)"
    install_cli "$old_rel"
    return 0
  fi

  log "Upgrading ${old_rev:0:12} -> ${new_rev:0:12}"
  local new_rel backup old_db migrated=0
  [[ "$new_rev" == "$old_rev" ]] && old_rel=""  # --force rebuild of the same commit: no separate release to fall back to
  new_rel="$(build_release "$new_rev")"          # the old release keeps serving while this builds
  backup="$(backup_db)"
  old_db="$(db_revision "$new_rel")"

  rollback() {
    warn "upgrade failed; rolling back"
    service_stop
    if [[ "$migrated" == 1 && -n "$old_db" ]]; then
      alembic_ "$new_rel" downgrade "$old_db" \
        || warn "could not downgrade the database schema; restore the backup: $backup"
    fi
    if [[ -n "$old_rel" ]]; then
      switch_to "$old_rel"
      rm -rf "$new_rel"
      service_start
      health_check || warn "the previous release did not come back up either; see: journalctl -u mealplan -n 50"
      die "rolled back to ${old_rev:0:12}. Database backup from before the upgrade: ${backup:-none}"
    fi
    die "upgrade failed. Database backup from before the upgrade: ${backup:-none}"
  }

  service_stop
  if ! alembic_ "$new_rel" upgrade head; then rollback; fi
  migrated=1
  switch_to "$new_rel"
  service_start
  health_check || rollback
  install_cli "$new_rel"
  prune_releases
  log "Upgraded to ${new_rev:0:12}; running at $(public_url)"
}

cmd_uninstall() {
  local purge=0
  while [[ $# -gt 0 ]]; do
    case "$1" in
      --purge) purge=1; shift ;;
      --yes|-y) ASSUME_YES=1; shift ;;
      *) die "unknown option for uninstall: $1" ;;
    esac
  done
  require_root
  if [[ -f "$STATE_FILE" ]]; then load_state; else DB_KIND="" CADDY_MANAGED=0; fi
  if [[ "$purge" == 1 ]]; then
    confirm "Remove Mealplan AND permanently delete its database, backups and configuration?" || die "aborted"
  else
    confirm "Remove Mealplan? (configuration, data and the database are kept)" || die "aborted"
  fi
  take_lock

  log "Stopping and removing the service"
  service_stop
  if ! test_mode; then
    systemctl disable mealplan >/dev/null 2>&1 || true
    rm -f "$UNIT_PATH"
    systemctl daemon-reload
  fi
  remove_caddy_site
  rm -rf "$PREFIX"
  rm -f "$BIN_PATH"

  if [[ "$purge" == 1 ]]; then
    if [[ "$DB_KIND" == postgres ]] && ! test_mode && command -v psql >/dev/null; then
      log "Dropping the PostgreSQL database and role"
      runuser -u postgres -- dropdb --if-exists "$SERVICE_USER" || warn "could not drop database $SERVICE_USER"
      runuser -u postgres -- dropuser --if-exists "$SERVICE_USER" || warn "could not drop role $SERVICE_USER"
    fi
    rm -rf "$ETC_DIR" "$VAR_DIR"
    if ! test_mode && id -u "$SERVICE_USER" >/dev/null 2>&1; then userdel "$SERVICE_USER" 2>/dev/null || true; fi
    log "Mealplan and all of its data have been removed"
  else
    log "Mealplan has been removed. Kept: $ETC_DIR, $VAR_DIR${DB_KIND:+ and the $DB_KIND database}"
    cat >&2 <<EOF
  Installing again reuses this data. To delete it as well, run the installer with:
    uninstall --purge
EOF
  fi
}

cmd_status() {
  load_state
  local rel rev state="not running"
  rel="$(current_release)"
  rev=unknown
  if [[ -n "$rel" && -f "$rel/REVISION" ]]; then rev="$(cut -c1-12 "$rel/REVISION")"; fi
  if test_mode; then
    [[ -f "$VAR_DIR/test-server.pid" ]] && kill -0 "$(cat "$VAR_DIR/test-server.pid")" 2>/dev/null && state="running"
  else
    state="$(systemctl is-active mealplan 2>/dev/null || true)"
  fi
  printf 'Version:   %s (branch %s)\nService:   %s\nURL:       %s\nDatabase:  %s\nConfig:    %s\nBackups:   %s\n' \
    "$rev" "$BRANCH" "$state" "$(public_url)" "$DB_KIND" "$ENV_FILE" "$BACKUP_DIR"
  if health_check_once; then echo "Health:    ok"; else echo "Health:    not responding"; fi
}

health_check_once() { curl -fsS -m 3 "http://127.0.0.1:$(env_value MEALPLAN_PORT)/api/health" >/dev/null 2>&1; }

cmd_backup() {
  require_root
  load_state
  take_lock
  local out
  out="$(backup_db)"
  [[ -n "$out" ]] || warn "nothing to back up yet"
}

main() {
  local cmd="${1:-install}"
  [[ $# -gt 0 ]] && shift
  case "$cmd" in
    install) cmd_install "$@" ;;
    upgrade|update) cmd_upgrade "$@" ;;
    uninstall|remove) cmd_uninstall "$@" ;;
    status) cmd_status "$@" ;;
    backup) cmd_backup "$@" ;;
    help|-h|--help) usage ;;
    -*) cmd_install "$cmd" "$@" ;;  # options without a command: install
    *) usage >&2; die "unknown command: $cmd" ;;
  esac
}

main "$@"
