#!/usr/bin/env bash
# Print launchd service status + health check (GET /healthz).
set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
# shellcheck source=scripts/lib.sh
source "${REPO_DIR}/scripts/lib.sh"

status_report
