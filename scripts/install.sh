#!/usr/bin/env bash
# Install podcast-transcriber as a launchd auto-start service (Phase 3).
#
#   1. creates .env from .env.template when .env is missing
#   2. generates ~/Library/LaunchAgents/com.podcasttranscriber.serve.plist
#      from deploy/com.podcasttranscriber.serve.plist (real repo path baked in)
#   3. loads the service (launchctl bootstrap, RunAtLoad starts it)
#   4. prints status + health check
set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
# shellcheck source=scripts/lib.sh
source "${REPO_DIR}/scripts/lib.sh"

echo "==> podcast-transcriber launchd install"
echo "    repo : ${REPO_DIR}"
echo "    user : $(id -un)"

require_pt_bin
mkdir -p "${LOG_DIR}"

if [[ ! -f "${REPO_DIR}/.env" ]]; then
  cp "${REPO_DIR}/.env.template" "${REPO_DIR}/.env"
  echo "    created ${REPO_DIR}/.env from .env.template"
  echo "    (edit .env and run scripts/restart.sh to apply changes)"
else
  echo "    ${REPO_DIR}/.env already exists; leaving it untouched"
fi

generate_plist
load_plist
start_service
wait_healthy || true

status_report
echo
echo "==> install complete"
echo "    service auto-starts at login (KeepAlive on crash)"
echo "    logs: ${LOG_DIR}/serve.out.log and serve.err.log"
