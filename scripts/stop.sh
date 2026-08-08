#!/usr/bin/env bash
# Stop the launchd service: unload it from launchd (process terminated).  The
# plist FILE is kept, so scripts/start.sh or scripts/install.sh bring it back.
# (A KeepAlive job restarts on SIGTERM, so "stop" must boot it out of launchd.)
set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
# shellcheck source=scripts/lib.sh
source "${REPO_DIR}/scripts/lib.sh"

stop_service
