#!/usr/bin/env bash
# Expose the web UI on the Tailnet for iPhone access (Phase 3).
#
# Idempotent: if `tailscale serve` already proxies port $PT_PORT it only
# prints the URL; otherwise it enables `tailscale serve --bg --https=<port>`
# (an HTTPS proxy of 127.0.0.1:<port>, tailnet-only) bound to OUR OWN https
# port so it can never collide with -- or overwrite -- the port-443/root
# serve entry another app may be using (e.g. the existing :20128 proxy).
#
# NEVER touches other serve entries -- this script only adds/checks the
# entry for our own https port.
set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
# shellcheck source=scripts/lib.sh
source "${REPO_DIR}/scripts/lib.sh"

TS_BIN="${TS_BIN:-/Applications/Tailscale.app/Contents/MacOS/Tailscale}"
PORT="${PT_PORT:-8765}"

if [[ ! -x "${TS_BIN}" ]]; then
  echo "error: Tailscale CLI not found at ${TS_BIN} (set TS_BIN to override)" >&2
  exit 1
fi

if ! "${TS_BIN}" status >/dev/null 2>&1; then
  echo "error: tailscale is not up (open the Tailscale app / run 'tailscale up')" >&2
  exit 1
fi

# Already served? Look for a Web handler whose key ends with ":<port>".
existing="$("${TS_BIN}" serve status --json 2>/dev/null \
  | jq -e --arg port ":${PORT}" \
      '.Web | to_entries[] | select(.key | endswith($port)) | .key' 2>/dev/null \
  || true)"

if [[ -n "${existing}" ]]; then
  echo "tailscale serve already enabled for port ${PORT}:"
  echo "  ${existing}"
else
  echo "enabling tailscale serve for port ${PORT} (proxying 127.0.0.1:${PORT})..."
  # --https=${PORT} binds OUR port as an https port: the entry is
  # https://<machine>.ts.net:${PORT}/ and the port-443/root entry (used by
  # other apps, e.g. :20128) is left untouched.
  "${TS_BIN}" serve --yes --bg --https="${PORT}" "http://127.0.0.1:${PORT}"
  echo "done."
fi

magic="$("${TS_BIN}" status --json | jq -r '.Self.DNSName' | sed 's/\.$//')"
if [[ -z "${magic}" ]]; then
  echo "error: could not determine this machine's tailnet hostname" >&2
  exit 1
fi

echo
echo "iPhone URL: https://${magic}:${PORT}"
echo "  tailnet-only: reachable from devices on the same tailnet."
echo "  if PT_AUTH_TOKEN is set, sign in from the phone with that token."
echo "  revoke (removes ONLY our port; leaves the :20128 proxy and others):"
echo "    ${TS_BIN} serve --https=${PORT} off"
