# Deployment & Operations Runbook (Phase 3 + Phase 4)

This document covers running podcast-transcriber as a macOS background service
(launchd), exposing it to an iPhone over Tailscale, and the day-to-day
operations: start/stop/status, logs, `pt doctor`, upgrades, and
troubleshooting (including the Phase 4 rate limit / queue cap).

Everything lives in the repo; there are no cloud dependencies.

---

## 1. One-time install

From the repo root:

```bash
scripts/install.sh
```

`install.sh` does, in order:

1. Creates `.env` from `.env.template` when `.env` does not exist yet
   (existing `.env` is left untouched).
2. Generates `~/Library/LaunchAgents/com.podcasttranscriber.serve.plist` from
   the `deploy/com.podcasttranscriber.serve.plist` template, baking in the real
   repo path, home dir and user name.
3. Loads the service via `launchctl bootstrap gui/<uid>` (falls back to
   `launchctl load`). `RunAtLoad=true` starts it immediately.
4. Prints the service status and the `/healthz` result.

The service then auto-starts at every login and is restarted by launchd if it
crashes or exits with an error (`KeepAlive`).

Requirements before installing:

- Python 3.10+ and the repo venv ready:
  `python -m venv .venv && .venv/bin/pip install -e .`
- `ffmpeg`/`ffprobe` on PATH (the plist sets
  `/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin`, which covers the standard
  Homebrew location).
- `jq` for `scripts/tailscale-serve.sh` (macOS lacks it — `brew install jq`).
- Port 8765 free (or change `PT_PORT` in `.env` first).

## 2. Configuration (`.env`)

All configuration comes from the repo-root `.env` (see `.env.template` for the
full, commented list). The plist deliberately does **not** bake PT_* values
into launchd: `pt serve` loads the repo `.env` itself at startup, so changing
`.env` and running `scripts/restart.sh` is all you need — no reinstall, no
plist regeneration.

| Variable                | Default                        | Meaning                                          |
|-------------------------|--------------------------------|--------------------------------------------------|
| `PT_HOST`               | `127.0.0.1`                    | Bind address for `pt serve`                      |
| `PT_PORT`               | `8765`                         | Web UI port                                      |
| `PT_AUTH_TOKEN`         | *(empty)*                      | Single-user auth token; empty = no auth          |
| `PT_RATE_LIMIT_PER_MIN` | `10`                           | Max `POST /jobs` per client IP per minute (429 + Retry-After) |
| `PT_MAX_QUEUED`         | `50`                           | Max PENDING+QUEUED jobs before new jobs are rejected (409) |
| `PT_TRUST_PROXY`        | `false`                        | Trust `X-Forwarded-For` for rate limiting        |
| `PT_MODEL`              | `mlx-community/whisper-small-mlx` | MLX Whisper model for transcription          |
| `PT_DATA_DIR`           | `data`                         | SQLite DB + audio + cache directory              |
| `PT_MAX_DOWNLOAD_BYTES` | `1073741824` (1 GiB)           | Max bytes accepted for episode audio downloads   |
| `PT_WORKER_STOP_TIMEOUT`| `5`                            | Seconds the worker waits on stop before failing the in-flight job |
| `PT_CHUNK_MINUTES`      | `10`                           | Transcription chunk length (minutes)             |
| `PT_TOP_RESULTS`        | `25`                           | iTunes Search API result limit                   |
| `PT_DURATION_TOLERANCE` | `600` (s)                      | Episode-match duration tolerance                 |

Generate a strong auth token with:

```bash
openssl rand -hex 32
```

## 3. Start / stop / status / logs

```bash
scripts/status.sh     # launchd state + /healthz probe
scripts/start.sh      # ensure loaded, then start (kickstart)
scripts/stop.sh       # stop the service (boots the job OUT of launchd; the
                      # plist FILE is kept, but autostart is suspended until
                      # start.sh / install.sh re-bootstrap it)
scripts/restart.sh    # stop + start + status (use after .env edits / upgrades)
scripts/logs.sh       # tail logs/serve.out.log + logs/serve.err.log (Ctrl-C quits)
scripts/logs.sh 500   # tail with a specific line count
```

`scripts/install.sh` can be re-run any time — it regenerates the plist and
reloads the service (idempotent).

## 4. Uninstall

```bash
scripts/uninstall.sh                # stop + unload + delete the plist, keep logs
scripts/uninstall.sh --delete-logs  # also remove logs/
```

## 5. Upgrading (pull new code)

```bash
git pull
.venv/bin/pip install -e .          # refresh the console script / deps
scripts/restart.sh                  # apply the new code to the running service
scripts/status.sh                   # confirm healthy
```

SQLite schema migrations run automatically on startup (`schema_version` table
in `store.py`), so no manual migration step is needed.

## 6. iPhone access over Tailscale (optional)

```bash
scripts/tailscale-serve.sh
```

This is idempotent:

- If `tailscale serve` already proxies our port (`$PT_PORT`, default 8765), it
  only prints the URL.
- Otherwise it enables `tailscale serve --yes --bg --https=8765
  http://127.0.0.1:8765` — an HTTPS proxy of `127.0.0.1:8765` bound to our own
  https port, reachable **only** from devices on the same tailnet.
- It never touches other serve entries (e.g. the existing `:20128` proxy on
  this machine); it only checks/adds an entry for our own port.

It prints the iPhone URL, e.g.
`https://donovins-macbook-pro.taila94639.ts.net:8765`.

> **Security note:** `tailscale serve` exposes the web UI to every device on
> the tailnet. Set `PT_AUTH_TOKEN` (see `.env.template`) before enabling it —
> the iPhone will sign in with that token once.

> **Cookie `Secure` flag (Phase 4):** when the app binds to a non-loopback
> interface (`--host 0.0.0.0`, LAN, etc.), the `pt_token` cookie is set with
> `Secure`. With the standard setup here (app on `127.0.0.1` + Tailscale HTTPS
> proxy) the cookie stays `Secure`-less because it travels over the proxy's
> HTTPS — which is safe. If you bind the app directly to an exposed interface,
> serve it only over HTTPS (the cookie is `Secure` and plain HTTP won't send
> it).

To revoke tailnet access for our port only (other proxies untouched):

```bash
/Applications/Tailscale.app/Contents/MacOS/Tailscale serve --https=8765 off
```

If the Tailscale CLI is not at the default location, set `TS_BIN`:

```bash
TS_BIN=/custom/path/Tailscale scripts/tailscale-serve.sh
```

## 7. Troubleshooting

### Port 8765 is busy

```bash
lsof -nP -iTCP:8765 -sTCP:LISTEN
```

Either stop the other process or change `PT_PORT` in `.env` and run
`scripts/restart.sh` (and re-run `scripts/tailscale-serve.sh` to proxy the new
port). `tailscale-serve.sh` reads `$PT_PORT` from the repo `.env`, so it stays
in sync automatically.

### Service loaded but not running / keeps dying

```bash
scripts/logs.sh        # or: tail -50 logs/serve.err.log logs/serve.out.log
scripts/status.sh
```

`KeepAlive` restarts the service on crash or error exit, but a crash loop can
only be diagnosed from the logs. Common causes:

- missing `pt` binary (venv not installed) → run `.venv/bin/pip install -e .`
- bind failure (port busy / permission) → see above
- model download failure on first job → check network; the model downloads
  into `~/.cache/huggingface` on first use

### Model download problems

The MLX Whisper model (`PT_MODEL`) downloads from HuggingFace into
`~/.cache/huggingface` on first use and needs network. Retry a failed job via
the web UI or `pt transcribe <job_id>`. A partially downloaded model can be
cleared with `rm -rf ~/.cache/huggingface/hub/models--mlx-community--whisper-*`.

### "database is locked" / SQLite errors

The DB is SQLite in WAL mode (`data/podcast_transcriber.db`) with one active
writer per database by design. If you see lock errors:

1. Confirm no second process is writing to the same DB:
   `lsof data/podcast_transcriber.db*`
2. Restart the service (`scripts/restart.sh`) — the worker's
   stale-RUNNING sweep and crash recovery run at startup.
3. As a last resort, back up and remove the WAL/SHM sidecar files
   (`podcast_transcriber.db-wal`, `-shm`) while the service is stopped.

### HTTP 429 "Too many requests" (rate limit)

`POST /jobs` is limited per client IP to `PT_RATE_LIMIT_PER_MIN`
(default 10) submissions per minute (sliding window). Over the limit you get
HTTP 429 with a `Retry-After` header. The iPhone/curl client just needs to
wait — every submission counts, including failed ones, so a script hammering
the endpoint will 429 for a while. To raise the ceiling, increase
`PT_RATE_LIMIT_PER_MIN` in `.env` and `scripts/restart.sh`. Only set
`PT_TRUST_PROXY=true` when the app sits behind a proxy you control (then
`X-Forwarded-For` is used to identify clients); otherwise the header is
ignored.

### HTTP 409 "Queue is full"

When `PENDING + QUEUED` jobs reach `PT_MAX_QUEUED` (default 50), new
submissions are rejected with HTTP 409 ("too many jobs queued") until the
worker drains some. Wait for the active transcription to finish, or clear
stuck queued jobs via `pt status` / the job list. `pt doctor` shows the
waiting-job count.

### Tailscale down / iPhone can't reach the app

```bash
scripts/tailscale-serve.sh     # re-checks and re-adds the proxy if needed
/Applications/Tailscale.app/Contents/MacOS/Tailscale status   # tailnet up?
```

The magic DNS name (e.g. `donovins-macbook-pro.taila94639.ts.net`) is
tailnet-specific; confirm it with
`tailscale status --json | jq -r '.Self.DNSName'`.

### Health check endpoint

`GET /healthz` is always public and returns:

```json
{"status":"ok","version":"0.1.0","db":"ok"}
```

`db` is `"error"` (HTTP 503) when the SQLite store cannot answer a trivial
`SELECT 1`. `scripts/status.sh` uses this probe.

## 8. Diagnostics with `pt doctor` (Phase 4)

```bash
.venv/bin/pt doctor
```

Runs local preflight checks and prints `[PASS]` / `[WARN]` / `[FAIL]` lines:

| Check            | PASS means…                                                  | WARN means… (does not fail)                              |
|------------------|--------------------------------------------------------------|----------------------------------------------------------|
| Python & venv    | `mlx_whisper` imports                                        | model import fails → transcription jobs will fail        |
| ffmpeg/ffprobe   | both binaries found                                          | — (FAIL when missing)                                    |
| Data dir & disk  | writable, ≥ 1 GiB free                                       | — (FAIL below 1 GiB)                                     |
| .env / PT_*      | at least one PT_* var set (values masked)                    | no PT_* set — defaults in use                            |
| Database         | DB opens, pings, schema v1                                   | — (FAIL when it cannot open/ping)                        |
| Worker state     | no RUNNING job                                               | RUNNING job(s) — possibly stale, see restart hint        |
| Tailscale        | CLI found, node up, serve entry for `PT_PORT` present        | CLI missing / node down / no serve entry (run `scripts/tailscale-serve.sh`) |
| launchd service  | loaded and running                                           | not loaded / loaded but stopped (run `scripts/install.sh`) |
| Model cache      | sized OK                                                     | —                                                       |

Exit code is `0` when nothing FAILs, `1` when any check FAILs. Run it first
whenever the iPhone cannot reach the app or a job misbehaves.

## 9. Rollback

See `docs/rollback.md` for a step-by-step rollback to the previous commit.

## 10. Logs & files layout

```
logs/                        # launchd stdout/stderr (serve.out.log / serve.err.log)
deploy/com.podcasttranscriber.serve.plist   # plist TEMPLATE (paths templated)
~/Library/LaunchAgents/com.podcasttranscriber.serve.plist  # generated at install
.env                         # local config (git-ignored); created from .env.template
data/podcast_transcriber.db  # SQLite (WAL) — see docs/architecture.md
```
