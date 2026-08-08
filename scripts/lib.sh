#!/usr/bin/env bash
# Shared helpers for the podcast-transcriber ops scripts.  Source me, don't run.
#
#   source "$(dirname "${BASH_SOURCE[0]}")/lib.sh"
set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PLIST_NAME="com.podcasttranscriber.serve"
PLIST_SRC="${REPO_DIR}/deploy/${PLIST_NAME}.plist"
PLIST_DST="${HOME}/Library/LaunchAgents/${PLIST_NAME}.plist"
LOG_DIR="${REPO_DIR}/logs"
PT_BIN="${REPO_DIR}/.venv/bin/pt"
LAUNCHD_DOMAIN="gui/$(id -u)"

# Honour PT_* from the repo .env (if present) so the scripts agree with the
# server's own configuration (PT_PORT, PT_HOST, ...) no matter which shell or
# CWD they are run from.
if [[ -f "${REPO_DIR}/.env" ]]; then
  set -a
  # shellcheck disable=SC1091
  source "${REPO_DIR}/.env"
  set +a
fi

PT_HOST="${PT_HOST:-127.0.0.1}"
PT_PORT="${PT_PORT:-8765}"
HEALTH_URL="http://${PT_HOST}:${PT_PORT}/healthz"

require_plist_src() {
  if [[ ! -f "${PLIST_SRC}" ]]; then
    echo "error: template not found: ${PLIST_SRC}" >&2
    exit 1
  fi
}

require_pt_bin() {
  if [[ ! -x "${PT_BIN}" ]]; then
    echo "error: ${PT_BIN} not found -- run '.venv/bin/pip install -e .' first" >&2
    exit 1
  fi
}

plist_loaded() {
  launchctl print "${LAUNCHD_DOMAIN}/${PLIST_NAME}" >/dev/null 2>&1
}

service_pid() {
  launchctl list 2>/dev/null | awk -v l="${PLIST_NAME}" '$3 == l {print $1}'
}

service_running() {
  local pid
  pid="$(service_pid)"
  [[ -n "${pid}" && "${pid}" != "-" ]]
}

generate_plist() {
  require_plist_src
  mkdir -p "$(dirname "${PLIST_DST}")"
  sed -e "s|__REPO_DIR__|${REPO_DIR}|g" \
      -e "s|__HOME_DIR__|${HOME}|g" \
      -e "s|__USER_NAME__|$(id -un)|g" \
      "${PLIST_SRC}" > "${PLIST_DST}"
  chmod 644 "${PLIST_DST}"
  echo "generated ${PLIST_DST}"
}

load_plist() {
  if plist_loaded; then
    echo "service ${PLIST_NAME} already loaded"
    return 0
  fi
  require_plist_src
  if [[ ! -f "${PLIST_DST}" ]]; then
    generate_plist
  fi
  if launchctl bootstrap "${LAUNCHD_DOMAIN}" "${PLIST_DST}" 2>/dev/null; then
    echo "service ${PLIST_NAME} bootstrapped (RunAtLoad: started)"
  else
    launchctl load "${PLIST_DST}"
    echo "service ${PLIST_NAME} loaded (fallback launchctl load)"
  fi
}

unload_plist() {
  if ! plist_loaded; then
    echo "service ${PLIST_NAME} not loaded"
    return 0
  fi
  if launchctl bootout "${LAUNCHD_DOMAIN}" "${PLIST_DST}" 2>/dev/null; then
    echo "service ${PLIST_NAME} unloaded"
  else
    launchctl unload "${PLIST_DST}"
    echo "service ${PLIST_NAME} unloaded (fallback launchctl unload)"
  fi
}

start_service() {
  if ! plist_loaded; then
    load_plist
  fi
  if service_running; then
    echo "service ${PLIST_NAME} already running (pid $(service_pid))"
    return 0
  fi
  if launchctl kickstart "${LAUNCHD_DOMAIN}/${PLIST_NAME}" 2>/dev/null; then
    echo "service ${PLIST_NAME} started (launchctl kickstart)"
  else
    launchctl start "${PLIST_NAME}"
    echo "service ${PLIST_NAME} started (launchctl start fallback)"
  fi
}

stop_service() {
  # A KeepAlive job is restarted by launchd the moment it exits, so SIGTERM
  # alone can never stop it.  Boot the service OUT of launchd instead (this
  # terminates the process); the plist FILE is kept so scripts/start.sh or
  # scripts/install.sh can bring it back.  Autostart-at-login is therefore
  # suspended while stopped -- the correct semantic for a real "stop".
  if ! plist_loaded; then
    echo "service ${PLIST_NAME} not loaded -- nothing to stop"
    return 0
  fi
  echo "stopping ${PLIST_NAME} (unloading from launchd; plist file kept)..."
  if launchctl bootout "${LAUNCHD_DOMAIN}" "${PLIST_DST}" 2>/dev/null; then
    echo "service ${PLIST_NAME} stopped (plist kept: ${PLIST_DST})"
  else
    launchctl unload "${PLIST_DST}"
    echo "service ${PLIST_NAME} stopped (launchctl unload fallback)"
  fi
}

health_check() {
  local out
  if ! out="$(curl -fsS -m 5 "${HEALTH_URL}" 2>&1)"; then
    echo "health: DOWN (curl failed: ${out})"
    return 1
  fi
  echo "health: ${out}"
}

# Wait up to ~12s for /healthz to answer after (re)starting the service, so
# status_report right after start does not race uvicorn's bind/startup.
wait_healthy() {
  for _ in $(seq 1 24); do
    if health_check >/dev/null 2>&1; then
      return 0
    fi
    sleep 0.5
  done
  echo "warning: /healthz did not answer within 12s" >&2
  return 1
}

status_report() {
  echo
  echo "==> launchd service status"
  if plist_loaded; then
    local pid
    pid="$(service_pid)"
    echo "    loaded  : yes"
    if [[ -n "${pid}" && "${pid}" != "-" ]]; then
      echo "    running : yes (pid ${pid})"
    else
      echo "    running : no"
    fi
    echo "    label   : ${PLIST_NAME}"
    echo "    plist   : ${PLIST_DST}"
  else
    echo "    loaded  : no"
  fi
  echo
  echo "==> health check (${HEALTH_URL})"
  if health_check; then
    echo "    -> OK"
  else
    echo "    -> DOWN (logs: ${LOG_DIR}/serve.out.log and serve.err.log)"
  fi
}
