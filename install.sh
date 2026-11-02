#!/usr/bin/env bash
# Mealplan installer, upgrader and uninstaller (Linux, systemd).
#
# Run it as root for a system-wide install, or as a normal user for a per-user
# install that needs no root at all:
#
#   System-wide:  curl -fsSL https://raw.githubusercontent.com/nktech1135/meal-planner/main/install.sh | sudo bash
#                 curl -fsSL https://raw.githubusercontent.com/nktech1135/meal-planner/main/install.sh | sudo bash -s -- install --domain meals.example.com
#   Per-user:     curl -fsSL https://raw.githubusercontent.com/nktech1135/meal-planner/main/install.sh | bash
#   From a checkout:  ./install.sh install   (or: sudo ./install.sh install)
#   Afterwards:   [sudo] mealplan upgrade | uninstall [--purge] | status | restart | backup | help
#
# The app itself only ever listens on 127.0.0.1. System-wide, Caddy is installed in
# front of it: plain HTTP on port 80, or HTTPS with an automatic certificate when
# --domain is given. Per-user installs (no root, so no ports 80/443) stay local.
#
# System-wide layout (Debian/Ubuntu; PostgreSQL by default; Caddy in front):
#   /opt/mealplan/             code and toolchain (releases/<rev>, current -> releases/<rev>, tools/, repo.git)
#   /etc/mealplan/mealplan.env configuration (kept on upgrade and plain uninstall)
#   /var/lib/mealplan/         data: SQLite database (if used) and backups/
#   mealplan.service           systemd unit, runs as the "mealplan" system user
#
# Per-user layout (any distribution; SQLite; systemd user service):
#   ~/.local/share/mealplan/app/    code and toolchain
#   ~/.config/mealplan/             configuration
#   ~/.local/share/mealplan/data/   database and backups/
#   ~/.config/systemd/user/mealplan.service, ~/.local/bin/mealplan
#   Without a systemd user manager (or with MEALPLAN_SERVICE=process) the app runs as
#   a plain background process instead; it then won't restart after a reboot.
#
# Everything runs inside functions and main() is called on the last line, so a
# partially downloaded script does nothing.

set -Eeuo pipefail
umask 022

# --- Pinned settings -----------------------------------------------------------
# Where the code is published (a fork can change this, or pass --repo).
DEFAULT_REPO="https://github.com/nktech1135/meal-planner.git"
DEFAULT_BRANCH="main"
DEFAULT_PORT=8080

UV_VERSION="0.11.25"
UV_SHA256_x86_64="1db18b5e76fa645a7f3865773139bdec8e2d46adbdbb35e7410b34fa8015ccd2"
UV_SHA256_aarch64="e0e9d73f74e06a7dcd53910d5962146ab48f0af9c92cc8df33a37baa0121014d"
NODE_VERSION="24.22.2"
NODE_SHA256_x64="48cc0e21e048790e54c0cf5749c2725005313d652651c40b7a21feb9697aaf75"
NODE_SHA256_arm64="eb187837a2230d4047161ac0be008584e16b46f726e9c9490ee35dc6b17d9ba8"
KEEP_BACKUPS=10

# --- Mode and paths -------------------------------------------------------------
# MODE is "system" when run as root and "user" otherwise. MEALPLAN_TEST_ROOT selects
# "test": system-style paths relocated under one directory, nothing that needs root,
# and the server run as a plain background process. For development only.
TEST_ROOT="${MEALPLAN_TEST_ROOT:-}"
SERVICE_USER="mealplan"
if [[ -n "$TEST_ROOT" ]]; then MODE="test"
elif [[ $EUID -eq 0 ]]; then MODE=system
else MODE=user; fi

if [[ "$MODE" == user ]]; then
  # `su`, `sudo -u` and some SSH setups leave XDG_RUNTIME_DIR pointing elsewhere,
  # which breaks `systemctl --user`. Use this user's runtime dir when it exists.
  if [[ ! -S "${XDG_RUNTIME_DIR:-/nonexistent}/bus" && -S "/run/user/$EUID/bus" ]]; then
    export XDG_RUNTIME_DIR="/run/user/$EUID" DBUS_SESSION_BUS_ADDRESS="unix:path=/run/user/$EUID/bus"
  fi
  DATA_HOME="${XDG_DATA_HOME:-$HOME/.local/share}"
  CONFIG_HOME="${XDG_CONFIG_HOME:-$HOME/.config}"
  PREFIX="$DATA_HOME/mealplan/app"
  ETC_DIR="$CONFIG_HOME/mealplan"
  VAR_DIR="$DATA_HOME/mealplan/data"
  BIN_PATH="$HOME/.local/bin/mealplan"
  UNIT_PATH="$CONFIG_HOME/systemd/user/mealplan.service"
  LOCK_FILE="${XDG_RUNTIME_DIR:-/tmp}/mealplan-$EUID.lock"
  SUDO=""
else
  PREFIX="$TEST_ROOT/opt/mealplan"
  ETC_DIR="$TEST_ROOT/etc/mealplan"
  VAR_DIR="$TEST_ROOT/var/lib/mealplan"
  BIN_PATH="$TEST_ROOT/usr/local/sbin/mealplan"
  UNIT_PATH="$TEST_ROOT/etc/systemd/system/mealplan.service"
  LOCK_FILE="$TEST_ROOT/run/lock/mealplan.lock"
  SUDO="sudo "
fi
CADDYFILE="/etc/caddy/Caddyfile"
CADDY_SITE="/etc/caddy/mealplan.caddy"
CADDYFILE_ORIG="/etc/caddy/Caddyfile.before-mealplan"  # the packaged Caddyfile, when the installer replaced it
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
die()  { printf '%serror:%s %s\n' "$C_ERR" "$C_OFF" "$*" >&2; exit "$DIED"; }
DIED=3  # die's exit status, so a die inside $(...) isn't reported a second time below
on_err() {
  (($1 == DIED)) && return
  printf '%serror:%s command failed (line %s): %s\n' "$C_ERR" "$C_OFF" "$2" "$3" >&2
}
trap 'on_err "$?" "$LINENO" "$BASH_COMMAND"' ERR

is_system() { [[ "$MODE" == system ]]; }
git_() { git -c safe.directory='*' "$@"; }

usage() {
  cat <<'EOF'
Usage: mealplan <command> [options]

Run as root (sudo) for the system-wide install, or as yourself for a per-user install.

Commands:
  install     Install Mealplan (default when no command is given)
                --port N         port the app listens on at 127.0.0.1 (default 8080)
                --repo URL|PATH  git repository to install from
                --branch NAME    branch to track (default main)
              System-wide only:
                --domain NAME    serve over HTTPS at NAME (DNS must point here); without it,
                                 Caddy serves plain HTTP on port 80
                --db postgres|sqlite   database (default postgres, or sqlite on machines with
                                 under 1 GB of memory; per-user always uses sqlite)
              Per-user only:
                --no-linger      don't keep running after you log out / start at boot
  upgrade     Upgrade to the latest commit of the tracked branch
                --ref REF        a specific branch, tag or commit instead
                --force          rebuild even if already at that commit
  uninstall   Remove the app; keeps config, data and the database
                --purge          also delete config, data, backups, database and the service user
                --yes            don't ask for confirmation
  status      Show installed version, service state and URL
  restart     Restart the app (e.g. after editing the configuration)
  backup      Back up the database now
  reset-link EMAIL   Print a one-time password reset link (for a locked-out admin)
  make-admin EMAIL   Give an account admin rights
  help        Show this help
EOF
}

# --- Checks ----------------------------------------------------------------------
require_commands() {
  local missing=() cmd
  for cmd in git curl tar xz sha256sum flock base64 find sed awk; do
    command -v "$cmd" >/dev/null 2>&1 || missing+=("$cmd")
  done
  ((${#missing[@]} == 0)) || die "missing required programs: ${missing[*]} (ask an administrator to install them, e.g. apt install git curl xz-utils)"
}

require_platform() {
  if ! is_system; then require_commands; return 0; fi
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
  mkdir -p "$(dirname "$LOCK_FILE")"
  exec 9>"$LOCK_FILE"
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
    printf 'REPO=%q\nBRANCH=%q\nDB_KIND=%q\nDOMAIN=%q\nCADDY_MANAGED=%q\nCADDYFILE_REPLACED=%q\nSERVICE_KIND=%q\n' \
      "$REPO" "$BRANCH" "$DB_KIND" "$DOMAIN" "$CADDY_MANAGED" "$CADDYFILE_REPLACED" "$SERVICE_KIND"
  } >"$STATE_FILE"
}

load_state() {
  if [[ ! -f "$STATE_FILE" ]]; then
    if [[ "$MODE" == user && -f /etc/mealplan/install.conf ]]; then
      die "Mealplan is installed system-wide; use: sudo mealplan ${CMD:-<command>}"
    fi
    die "Mealplan is not installed${MODE:+ ($MODE mode: no $STATE_FILE)}"
  fi
  # shellcheck disable=SC1090
  . "$STATE_FILE"
  SERVICE_KIND="${SERVICE_KIND:-$(default_service_kind)}"
  CADDY_MANAGED="${CADDY_MANAGED:-0}" CADDYFILE_REPLACED="${CADDYFILE_REPLACED:-0}"
}

env_value() {  # env_value KEY -> value from the config file
  sed -n "s/^$1=//p" "$ENV_FILE" | tail -n1
}

# --- System setup ----------------------------------------------------------------
install_packages() {
  is_system || return 0
  local pkgs=(ca-certificates curl git tar xz-utils util-linux caddy)
  [[ "$DB_KIND" == postgres ]] && pkgs+=(postgresql)
  log "Installing system packages: ${pkgs[*]}"
  export DEBIAN_FRONTEND=noninteractive
  apt-get update -qq
  apt-get install -y -qq --no-install-recommends "${pkgs[@]}" >/dev/null
}

ensure_user() {
  is_system || return 0
  if ! id -u "$SERVICE_USER" >/dev/null 2>&1; then
    log "Creating system user $SERVICE_USER"
    useradd --system --user-group --home-dir "$VAR_DIR" --no-create-home --shell /usr/sbin/nologin "$SERVICE_USER"
  fi
}

make_dirs() {
  mkdir -p "$PREFIX" "$TOOLS" "$CACHE" "$RELEASES" "$(dirname "$BIN_PATH")"
  if is_system; then
    install -d -m 0750 -o root -g "$SERVICE_USER" "$ETC_DIR"
    install -d -m 0750 -o "$SERVICE_USER" -g "$SERVICE_USER" "$VAR_DIR" "$BACKUP_DIR"
  else
    mkdir -p "$ETC_DIR" "$BACKUP_DIR"
    chmod 0700 "$ETC_DIR" "$VAR_DIR"
  fi
}

as_service() {  # run a command as the service user, with the app's configuration loaded
  local script="set -a; . '$ENV_FILE'; set +a; $*"
  if is_system; then runuser -u "$SERVICE_USER" -- bash -c "$script"
  else bash -c "$script"; fi
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
  else
    log "Fetching updates from $REPO"
  fi
  git_ -C "$REPO_DIR" fetch --quiet --prune --tags origin '+refs/heads/*:refs/heads/*'
}

resolve_ref() {  # resolve_ref REF -> full commit id
  git_ -C "$REPO_DIR" rev-parse --verify --quiet "$1^{commit}" || die "unknown branch, tag or commit: $1"
}

pick_rev() {  # pick_rev BRANCH -> the newest commit on BRANCH
  resolve_ref "$1"
}

pick_ref() {  # pick_ref REF -> REF's commit
  resolve_ref "$1"
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

  build_web "$rel"
  [[ -f "$rel/frontend/dist/index.html" ]] || die "web interface build produced no index.html"
  echo "$rel"
}

# The web interface is built on each server: Node.js (pinned, checksum-verified, under $TOOLS) fetches
# the packages and esbuild bundles them, in about 300 MB of memory. node_modules is removed afterwards.
build_web() {  # build_web RELEASE
  local rel="$1"
  log "Building the web interface"
  install_node
  check_build_memory
  log "Downloading web interface packages"
  web_step "$rel" 900 "the package download" \
    npm ci --ignore-scripts --no-audit --no-fund --prefer-offline --fetch-timeout=60000 --fetch-retries=4
  log "Bundling the web interface"
  # Type-checking is part of ./test.sh; the server only needs the bundle (esbuild, about 130 MB).
  web_step "$rel" 900 "bundling" node build.mjs
  rm -rf "$rel/frontend/node_modules"
}

# Output goes to a log file rather than the screen, and a stalled step fails after LIMIT seconds
# with that log's tail, instead of sitting silently forever.
web_step() {  # web_step RELEASE LIMIT DESCRIPTION CMD...
  local rel="$1" limit="$2" what="$3" out="$1/web-build.log" rc=0 start=$SECONDS
  shift 3
  # exec and the outer braces keep the shell's "Killed" notice out of the log and off the screen.
  { (
    cd "$rel/frontend"
    exec env PATH="$TOOLS/node/bin:$PATH" npm_config_cache="$CACHE/npm" npm_config_update_notifier=false \
      timeout --kill-after=15 "$limit" "$@"
  ) >>"$out" 2>&1; } 2>/dev/null || rc=$?
  ((rc == 0)) && return 0
  tail -n 25 "$out" >&2
  if ((SECONDS - start >= limit)); then
    if [[ "$what" == bundling ]]; then
      die "$what took over $((limit / 60)) minutes and was stopped; the machine is probably short of memory (full log: $out)"
    fi
    die "$what took over $((limit / 60)) minutes and was stopped; check that this machine can reach https://registry.npmjs.org (a proxy, firewall or broken IPv6 can stall it). Full log: $out"
  fi
  ((rc == 137)) && die "$what was killed, most likely because the machine ran out of memory (adding swap helps). Full log: $out"
  die "$what failed (exit $rc, see above; full log: $out)"
}

BUILD_NEEDS_KB=$((350 * 1024))  # the build's measured peak (~300 MB) plus some room

free_memory_kb() {
  awk '/^(MemAvailable|SwapFree):/ {s += $2} END {print s + 0}' /proc/meminfo 2>/dev/null || echo 0
}

check_build_memory() {
  local kb
  kb="$(free_memory_kb)"
  if ((kb > 0 && kb < BUILD_NEEDS_KB)); then
    warn "only $((kb / 1024)) MB of memory is free; building the web interface needs about 300 MB, so it may be slow or fail (adding swap helps)"
  fi
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
# PostgreSQL takes 60-100 MB; on a small machine SQLite (inside the app process) leaves room for the app.
SMALL_MACHINE_KB=$((1024 * 1024))

default_db() {
  local kb
  kb="$(awk '/^MemTotal:/ {print $2}' /proc/meminfo 2>/dev/null || echo 0)"
  if ((kb > 0 && kb < SMALL_MACHINE_KB)); then
    log "This machine has $((kb / 1024)) MB of memory, so Mealplan will use SQLite rather than PostgreSQL (--db postgres to override)"
    echo sqlite
  else
    echo postgres
  fi
}

random_secret() { head -c 48 /dev/urandom | base64 -w0 | tr '+/' '-_' | tr -d '='; }

write_config() {
  if [[ -f "$ENV_FILE" ]]; then
    log "Keeping existing configuration $ENV_FILE"
    return 0
  fi
  local secure=false db_url
  [[ -n "$DOMAIN" ]] && secure=true
  if [[ "$DB_KIND" == postgres ]]; then
    db_url="postgresql+psycopg://$SERVICE_USER@/$SERVICE_USER?host=/var/run/postgresql"
  else
    db_url="sqlite:///$VAR_DIR/mealplan.db"
  fi
  log "Writing configuration $ENV_FILE"
  cat >"$ENV_FILE" <<EOF
# Mealplan bootstrap configuration, written by the installer.
#
# Everything else (API keys, the AI advisor, data sources, sign-ups, email) is set
# in the app: sign in as an admin and open Settings.
#
# SECRET_KEY signs sessions and encrypts the keys stored in Settings: keep it secret,
# and don't change it, or stored keys can no longer be read and must be entered again.
# After editing this file: ${SUDO}mealplan restart

MEALPLAN_HOST=127.0.0.1
MEALPLAN_PORT=$PORT
DATABASE_URL=$db_url
SECRET_KEY=$(random_secret)
COOKIE_SECURE=$secure
STATIC_DIR=$CURRENT/frontend/dist
${DOMAIN:+PUBLIC_URL=https://$DOMAIN}
EOF
  if is_system; then chown root:"$SERVICE_USER" "$ENV_FILE" && chmod 0640 "$ENV_FILE"
  else chmod 0600 "$ENV_FILE"; fi
}

setup_postgres() {
  [[ "$DB_KIND" == postgres ]] || return 0
  is_system || die "PostgreSQL needs the system-wide install; use --db sqlite"
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

caddyfile_is_stock() {  # unchanged from the caddy package?
  local changed
  changed="$(dpkg --verify caddy 2>/dev/null || true)"
  [[ "$changed" != *" $CADDYFILE"* ]]
}

setup_caddy() {
  is_system || return 0
  local address
  if [[ -n "$DOMAIN" ]]; then address="$DOMAIN"; log "Configuring Caddy for https://$DOMAIN"
  else address=":80"; log "Configuring Caddy for plain HTTP on port 80"; fi
  cat >"$CADDY_SITE" <<EOF
# Managed by the mealplan installer.
$address {
	encode gzip
	reverse_proxy 127.0.0.1:$PORT
}
EOF
  if [[ "${CADDYFILE_REPLACED:-0}" != 1 && -f "$CADDYFILE" ]] && caddyfile_is_stock; then
    # The packaged Caddyfile only serves a placeholder page on :80, which would clash with ours.
    # Keep it aside (restored on uninstall) and use our own. An edited Caddyfile is left alone.
    mv "$CADDYFILE" "$CADDYFILE_ORIG"
    printf '# Managed by the mealplan installer; the packaged file is in %s.\nimport %s\n' \
      "$CADDYFILE_ORIG" "$CADDY_SITE" >"$CADDYFILE"
    CADDYFILE_REPLACED=1
  elif ! grep -qxF "import $CADDY_SITE" "$CADDYFILE" 2>/dev/null; then
    printf '\nimport %s\n' "$CADDY_SITE" >>"$CADDYFILE"
  fi
  CADDY_MANAGED=1
  if ! caddy validate --config "$CADDYFILE" --adapter caddyfile >/dev/null 2>&1; then
    remove_caddy_site
    die "Caddy rejected the configuration: your existing $CADDYFILE probably already serves $address. Remove that site, or use --domain."
  fi
  systemctl enable caddy >/dev/null 2>&1
  systemctl reload caddy 2>/dev/null || systemctl restart caddy
  systemctl is-active --quiet caddy || die "Caddy did not start; is another web server using port 80 or 443? See: journalctl -u caddy"
}

remove_caddy_site() {
  [[ "${CADDY_MANAGED:-0}" == 1 ]] || return 0
  is_system || return 0
  rm -f "$CADDY_SITE"
  if [[ "${CADDYFILE_REPLACED:-0}" == 1 && -f "$CADDYFILE_ORIG" ]]; then
    mv "$CADDYFILE_ORIG" "$CADDYFILE"
  elif [[ -f "$CADDYFILE" ]]; then
    sed -i "\\|^import $CADDY_SITE\$|d" "$CADDYFILE"
  fi
  systemctl reload caddy 2>/dev/null || true
  CADDY_MANAGED=0 CADDYFILE_REPLACED=0
}

# Installs from before the app was always kept on 127.0.0.1 (and, system-wide, behind Caddy).
ensure_local_only() {
  local changed=0
  if [[ "$(env_value MEALPLAN_HOST)" != 127.0.0.1 ]]; then
    log "The app now listens on 127.0.0.1 only"
    sed -i 's/^MEALPLAN_HOST=.*/MEALPLAN_HOST=127.0.0.1/' "$ENV_FILE"
    changed=1
  fi
  if is_system && [[ "${CADDY_MANAGED:-0}" != 1 ]]; then
    install_packages
    PORT="$(env_value MEALPLAN_PORT)"
    setup_caddy
    save_state
  fi
  return $((1 - changed))  # success when the running service needs a restart
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
# SERVICE_KIND: "system" (systemd unit), "user" (systemd user unit), or "process"
# (plain background process: test mode, or per-user without a systemd user manager).
default_service_kind() {
  if [[ -n "${MEALPLAN_SERVICE:-}" && "$MODE" != system ]]; then
    [[ "$MEALPLAN_SERVICE" == user || "$MEALPLAN_SERVICE" == process ]] || die "MEALPLAN_SERVICE must be user or process"
    echo "$MEALPLAN_SERVICE"; return
  fi
  case "$MODE" in
    system) echo system ;;
    test) echo process ;;
    user) if systemctl --user show-environment >/dev/null 2>&1; then echo user; else echo process; fi ;;
  esac
}

systemctl_() {  # systemctl for this install's service manager
  if [[ "$SERVICE_KIND" == user ]]; then systemctl --user "$@"; else systemctl "$@"; fi
}

logs_hint() {
  case "$SERVICE_KIND" in
    system) echo "journalctl -u mealplan -n 50" ;;
    user) echo "journalctl --user -u mealplan -n 50" ;;
    process) echo "$VAR_DIR/server.log" ;;
  esac
}

exec_start() {
  # shellcheck disable=SC2016  # ${MEALPLAN_*} are expanded by systemd from the EnvironmentFile
  printf '"%s" app.main:app --host ${MEALPLAN_HOST} --port ${MEALPLAN_PORT} --proxy-headers --forwarded-allow-ips 127.0.0.1 --no-server-header' \
    "$CURRENT/venv/bin/uvicorn"
}

write_unit() {
  case "$SERVICE_KIND" in
    process) return 0 ;;
    user)
      mkdir -p "$(dirname "$UNIT_PATH")"
      cat >"$UNIT_PATH" <<EOF
# Managed by the mealplan installer.
[Unit]
Description=Mealplan meal and supplement tracker

[Service]
Type=simple
EnvironmentFile=$ENV_FILE
WorkingDirectory=$CURRENT/backend
ExecStart=$(exec_start)
Restart=on-failure
RestartSec=3
UMask=0077
NoNewPrivileges=true

[Install]
WantedBy=default.target
EOF
      ;;
    system)
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
ExecStart=$(exec_start)
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
      ;;
  esac
  systemctl_ daemon-reload
}

remove_unit() {
  [[ "$SERVICE_KIND" == process ]] && return 0
  systemctl_ disable mealplan >/dev/null 2>&1 || true
  rm -f "$UNIT_PATH"
  systemctl_ daemon-reload || true
}

ensure_linger() {
  # Without "linger", a user's services stop at logout and don't start at boot.
  [[ "$SERVICE_KIND" == user ]] || return 0
  local me
  me="$(id -un)"
  [[ "$(loginctl show-user "$me" -p Linger --value 2>/dev/null)" == yes ]] && return 0
  if [[ "${NO_LINGER:-0}" == 1 ]]; then
    warn "Mealplan will stop when you log out and won't start at boot (--no-linger)."
    return 0
  fi
  if loginctl enable-linger --no-ask-password "$me" 2>/dev/null; then
    log "Enabled lingering for $me so Mealplan keeps running after logout and starts at boot"
  else
    warn "could not enable lingering: Mealplan will stop when you log out and won't start at boot."
    warn "an administrator can fix that once with: sudo loginctl enable-linger $me"
  fi
}

service_stop() {
  if [[ "$SERVICE_KIND" == process ]]; then
    local pidfile="$VAR_DIR/server.pid"
    if [[ -f "$pidfile" ]]; then kill "$(cat "$pidfile")" 2>/dev/null || true; rm -f "$pidfile"; sleep 1; fi
  else
    systemctl_ stop mealplan 2>/dev/null || true
  fi
}

service_start() {
  if [[ "$SERVICE_KIND" == process ]]; then
    # Launched directly (not via a function, which would fork a wrapper) so $! is the server's PID,
    # and without fd 9 so the server doesn't hold the installer lock.
    nohup bash -c "set -a; . '$ENV_FILE'; set +a; cd '$CURRENT/backend' && exec '$CURRENT/venv/bin/uvicorn' app.main:app \
      --host \"\$MEALPLAN_HOST\" --port \"\$MEALPLAN_PORT\"" >>"$VAR_DIR/server.log" 2>&1 9>&- </dev/null &
    echo $! >"$VAR_DIR/server.pid"
  else
    systemctl_ enable mealplan >/dev/null 2>&1
    systemctl_ restart mealplan
  fi
}

# On a small machine the running app (~190 MB) and the build (~300 MB) don't fit side by side, so the
# app stops while the new release builds; if the build fails, the old release starts again on exit.
pause_for_build() {
  local kb
  kb="$(free_memory_kb)"
  [[ "$(service_state)" == active || "$(service_state)" == running ]] || return 0
  ((kb == 0 || kb >= BUILD_NEEDS_KB)) && return 0
  warn "only $((kb / 1024)) MB of memory is free, so Mealplan stops while the new version builds (a few minutes)"
  service_stop
  trap resume_after_build EXIT
}

resume_after_build() {
  [[ "$(service_state)" == active || "$(service_state)" == running ]] && return 0
  warn "starting the previous release again"
  service_start || true
}

service_state() {
  if [[ "$SERVICE_KIND" == process ]]; then
    if [[ -f "$VAR_DIR/server.pid" ]] && kill -0 "$(cat "$VAR_DIR/server.pid")" 2>/dev/null; then echo running
    else echo "not running"; fi
  else
    systemctl_ is-active mealplan 2>/dev/null || true
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
  if [[ "${CADDY_MANAGED:-0}" == 1 ]]; then
    local ip
    ip="$(hostname -I 2>/dev/null | awk '{print $1}')"
    echo "http://${ip:-localhost}"
    return
  fi
  echo "http://127.0.0.1:$(env_value MEALPLAN_PORT)"
}

# --- Commands --------------------------------------------------------------------------
cmd_install() {
  REPO="" BRANCH="$DEFAULT_BRANCH" DOMAIN="" PORT="$DEFAULT_PORT" DB_KIND="" CADDY_MANAGED=0 CADDYFILE_REPLACED=0
  while [[ $# -gt 0 ]]; do
    case "$1" in
      --repo) REPO="${2:?--repo needs a value}"; shift 2 ;;
      --branch) BRANCH="${2:?--branch needs a value}"; shift 2 ;;
      --domain) DOMAIN="${2:?--domain needs a value}"; shift 2 ;;
      --port) PORT="${2:?--port needs a value}"; shift 2 ;;
      --listen) die "--listen is no longer supported: the app only listens on 127.0.0.1 (system-wide, Caddy serves it to the network)" ;;
      --db) DB_KIND="${2:?--db needs a value}"; shift 2 ;;
      --no-linger) NO_LINGER=1; shift ;;
      --build-web) shift ;;  # always on now; accepted so older commands keep working
      --yes|-y) ASSUME_YES=1; shift ;;
      *) die "unknown option for install: $1 (see: mealplan help)" ;;
    esac
  done
  if is_system; then
    DB_KIND="${DB_KIND:-$(default_db)}"
  else
    [[ -z "$DOMAIN" ]] || die "--domain needs the system-wide install (HTTPS on ports 80/443 requires root); run with sudo"
    [[ "${DB_KIND:-sqlite}" == sqlite ]] || die "--db postgres needs the system-wide install; run with sudo"
    DB_KIND=sqlite
  fi
  if ! [[ "$PORT" =~ ^[0-9]+$ ]] || ((PORT < 1024 || PORT > 65535)); then die "--port must be 1024-65535"; fi
  [[ "$DB_KIND" == postgres || "$DB_KIND" == sqlite ]] || die "--db must be postgres or sqlite"
  [[ -z "$DOMAIN" || "$DOMAIN" =~ ^[A-Za-z0-9.-]+$ ]] || die "invalid --domain"
  [[ -n "$REPO" ]] || REPO="$(default_repo)"
  if [[ -d "$REPO" ]]; then REPO="$(cd "$REPO" && pwd)"; fi

  require_platform
  detect_arch
  if [[ -e "$CURRENT" ]]; then die "Mealplan is already installed; use: ${SUDO}mealplan upgrade"; fi
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
  local why
  SERVICE_KIND="$(default_service_kind)"
  if [[ "$MODE" == user && "$SERVICE_KIND" == process ]]; then
    if [[ -n "${MEALPLAN_SERVICE:-}" ]]; then why="MEALPLAN_SERVICE=process"; else why="no systemd user manager found"; fi
    warn "$why: Mealplan will run as a background process and won't restart after a reboot"
  fi
  install_packages
  ensure_user
  make_dirs
  install_uv
  fetch_source
  local rev rel
  rev="$(pick_rev "$BRANCH")"
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
  health_check || die "the service did not come up; see: $(logs_hint)"
  ensure_linger

  log "Mealplan ${rev:0:12} is running at $(public_url)"
  cat >&2 <<EOF

  Next steps, all in the app:
    1. Open $(public_url) and register. The first account becomes the admin.
    2. Settings: add an Anthropic API key (AI advisor) and a free USDA key.
    3. Settings → Data: import the USDA food databases (about a minute).
    4. Settings: turn off "Allow new sign-ups" once everyone has an account,
       or invite people from Settings → Users.

  Manage it with:  ${SUDO}mealplan status | restart | upgrade | backup | uninstall
EOF
  if [[ "$MODE" == user && ":$PATH:" != *":$(dirname "$BIN_PATH"):"* ]]; then
    warn "$(dirname "$BIN_PATH") is not on your PATH; run $BIN_PATH directly or add it to PATH"
  fi
  if is_system && [[ -z "$DOMAIN" ]]; then
    warn "Caddy serves plain HTTP on port 80. For use beyond a trusted network, reinstall with --domain for HTTPS (the camera barcode scanner also needs HTTPS)."
  elif ! is_system; then
    log "Listening on this machine only (127.0.0.1). For access from other machines, use the system-wide install (sudo), which puts Caddy in front."
  fi
}

cmd_upgrade() {
  local ref="" force=0
  while [[ $# -gt 0 ]]; do
    case "$1" in
      --ref) ref="${2:?--ref needs a value}"; shift 2 ;;
      --force) force=1; shift ;;
      --build-web) shift ;;  # always on now; accepted so older commands keep working
      *) die "unknown option for upgrade: $1" ;;
    esac
  done
  load_state
  detect_arch
  take_lock
  if ensure_local_only; then service_stop; service_start; health_check || die "the service did not come up; see: $(logs_hint)"; fi
  local old_rel old_rev new_rev
  old_rel="$(current_release)"
  [[ -n "$old_rel" ]] || die "no current release found under $PREFIX"
  old_rev="$(cat "$old_rel/REVISION")"
  install_uv
  fetch_source
  if [[ -n "$ref" ]]; then new_rev="$(pick_ref "$ref")"; else new_rev="$(pick_rev "$BRANCH")"; fi
  if [[ "$new_rev" == "$old_rev" && "$force" != 1 ]]; then
    log "Already at ${old_rev:0:12}; nothing to do (use --force to rebuild)"
    install_cli "$old_rel"
    return 0
  fi

  log "Upgrading ${old_rev:0:12} -> ${new_rev:0:12}"
  local new_rel backup old_db migrated=0
  [[ "$new_rev" == "$old_rev" ]] && old_rel=""  # --force rebuild of the same commit: no separate release to fall back to
  pause_for_build
  new_rel="$(build_release "$new_rev")"          # the old release keeps serving while this builds, memory permitting
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
      health_check || warn "the previous release did not come back up either; see: $(logs_hint)"
      die "rolled back to ${old_rev:0:12}. Database backup from before the upgrade: ${backup:-none}"
    fi
    die "upgrade failed. Database backup from before the upgrade: ${backup:-none}"
  }

  service_stop
  trap - EXIT  # from here on, rollback restarts the right release
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
  if [[ -f "$STATE_FILE" ]]; then load_state
  else DB_KIND="" CADDY_MANAGED=0 CADDYFILE_REPLACED=0 SERVICE_KIND="$(default_service_kind)"; fi
  if [[ "$purge" == 1 ]]; then
    confirm "Remove Mealplan AND permanently delete its database, backups and configuration?" || die "aborted"
  else
    confirm "Remove Mealplan? (configuration, data and the database are kept)" || die "aborted"
  fi
  take_lock

  log "Stopping and removing the service"
  service_stop
  remove_unit
  remove_caddy_site
  rm -rf "$PREFIX"
  rm -f "$BIN_PATH"

  if [[ "$purge" == 1 ]]; then
    if [[ "$DB_KIND" == postgres ]] && is_system && command -v psql >/dev/null; then
      log "Dropping the PostgreSQL database and role"
      runuser -u postgres -- dropdb --if-exists "$SERVICE_USER" || warn "could not drop database $SERVICE_USER"
      runuser -u postgres -- dropuser --if-exists "$SERVICE_USER" || warn "could not drop role $SERVICE_USER"
    fi
    rm -rf "$ETC_DIR" "$VAR_DIR"
    if [[ "$MODE" == user ]]; then rmdir "$(dirname "$VAR_DIR")" 2>/dev/null || true; fi
    if is_system && id -u "$SERVICE_USER" >/dev/null 2>&1; then userdel "$SERVICE_USER" 2>/dev/null || true; fi
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
  local rel rev state
  rel="$(current_release)"
  rev=unknown
  if [[ -n "$rel" && -f "$rel/REVISION" ]]; then rev="$(cut -c1-12 "$rel/REVISION")"; fi
  state="$(service_state)"
  printf 'Install:   %s (%s service)\nVersion:   %s (branch %s)\nService:   %s\nURL:       %s\nDatabase:  %s\nConfig:    %s\nBackups:   %s\nLogs:      %s\n' \
    "$MODE" "$SERVICE_KIND" "$rev" "$BRANCH" "$state" "$(public_url)" "$DB_KIND" "$ENV_FILE" "$BACKUP_DIR" "$(logs_hint)"
  if health_check_once; then echo "Health:    ok"; else echo "Health:    not responding"; fi
}

health_check_once() { curl -fsS -m 3 "http://127.0.0.1:$(env_value MEALPLAN_PORT)/api/health" >/dev/null 2>&1; }

cmd_restart() {
  load_state
  take_lock
  service_stop
  service_start
  health_check || die "the service did not come up; see: $(logs_hint)"
  log "Restarted; running at $(public_url)"
}

cmd_app() {  # cmd_app reset-link|make-admin EMAIL: run a server-side app command
  local action="$1" email="${2:-}"
  [[ -n "$email" ]] || die "usage: mealplan $action EMAIL"
  load_state
  [[ -n "$(current_release)" ]] || die "no current release found under $PREFIX"
  as_service "cd '$CURRENT/backend' && exec '$CURRENT/venv/bin/python' -m app.cli $action $(printf '%q' "$email")"
}

cmd_backup() {
  load_state
  take_lock
  local out
  out="$(backup_db)"
  [[ -n "$out" ]] || warn "nothing to back up yet"
}

main() {
  local cmd="${1:-install}"
  [[ $# -gt 0 ]] && shift
  CMD="$cmd"
  case "$cmd" in
    install) cmd_install "$@" ;;
    upgrade|update) cmd_upgrade "$@" ;;
    uninstall|remove) cmd_uninstall "$@" ;;
    status) cmd_status "$@" ;;
    restart) cmd_restart "$@" ;;
    backup) cmd_backup "$@" ;;
    reset-link|make-admin) cmd_app "$cmd" "$@" ;;
    help|-h|--help) usage ;;
    -*) cmd_install "$cmd" "$@" ;;  # options without a command: install
    *) usage >&2; die "unknown command: $cmd" ;;
  esac
}

main "$@"
