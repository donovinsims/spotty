#!/usr/bin/env bash
# Start the launchd service (bootstraps the plist; loads it first if needed).
# RunAtLoad starts it immediately; launchd keeps it alive afterwards.
set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
# shellcheck source=scripts/lib.sh
source "${REPO_DIR}/scripts/lib.sh"

if [[ ! -f "${PLIST_DST}" ]]; then
  echo "${PLIST_NAME} not installed yet -- running scripts/install.sh"
  exec "${REPO_DIR}/scripts/install.sh"
fi

require_pt_bin
mkdir -p "${LOG_DIR}"
start_service
wait_healthy || true
echo
echo "==> status"
status_report
