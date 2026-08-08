#!/usr/bin/env bash
# Tail the launchd service logs (Ctrl-C to quit).
#   scripts/logs.sh [lines]   default 100 lines
set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
# shellcheck source=scripts/lib.sh
source "${REPO_DIR}/scripts/lib.sh"

mkdir -p "${LOG_DIR}"
touch "${LOG_DIR}/serve.out.log" "${LOG_DIR}/serve.err.log"

LINES="${1:-100}"
exec tail -n "${LINES}" -f "${LOG_DIR}/serve.out.log" "${LOG_DIR}/serve.err.log"
