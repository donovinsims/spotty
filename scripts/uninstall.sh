#!/usr/bin/env bash
# Remove the launchd service: stop, unload, delete the plist.
#   scripts/uninstall.sh            keep logs
#   scripts/uninstall.sh --delete-logs   also remove logs/
set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
# shellcheck source=scripts/lib.sh
source "${REPO_DIR}/scripts/lib.sh"

echo "==> uninstalling ${PLIST_NAME} launchd service"

stop_service || true
unload_plist

if [[ -f "${PLIST_DST}" ]]; then
  rm -f "${PLIST_DST}"
  echo "removed ${PLIST_DST}"
else
  echo "no plist at ${PLIST_DST}"
fi

if [[ "${1:-}" == "--delete-logs" ]]; then
  rm -rf "${LOG_DIR}"
  echo "removed ${LOG_DIR}"
else
  echo "logs kept at ${LOG_DIR} (pass --delete-logs to remove them)"
fi

echo "done."
