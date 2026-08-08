#!/usr/bin/env bash
# Restart the launchd service (stop + start + status).
set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
# shellcheck source=scripts/lib.sh
source "${REPO_DIR}/scripts/lib.sh"

echo "==> restarting ${PLIST_NAME}"
stop_service || true
sleep 1
start_service
wait_healthy || true
status_report
