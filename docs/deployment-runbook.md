# Deployment & Operations Runbook (Phase 3)

This document covers running podcast-transcriber as a macOS background service
(launchd), exposing it to an iPhone over Tailscale, and the day-to-day
operations: start/stop/status, logs, upgrades, and troubleshooting.

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
scripts/stop.sh       # SIGTERM the service (plist stays loaded; autostart kept)
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
- Otherwise it enables `tailscale serve --bg 8765` — an HTTPS proxy of
  `127.0.0.1:8765`, reachable **only** from devices on the same tailnet.
- It never touches other serve entries (e.g. the existing `:20128` proxy on
  this machine); it only checks/adds an entry for our own port.

It prints the iPhone URL, e.g.
`https://donovins-macbook-pro.taila94639.ts.net:8765`.

> **Security note:** `tailscale serve` exposes the web UI to every device on
> the tailnet. Set `PT_AUTH_TOKEN` (see `.env.template`) before enabling it —
> the iPhone will sign in with that token once.

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

## 8. Rollback

See `docs/rollback.md` for a step-by-step rollback to the previous commit.

## 9. Logs & files layout

```
logs/                        # launchd stdout/stderr (serve.out.log / serve.err.log)
deploy/com.podcasttranscriber.serve.plist   # plist TEMPLATE (paths templated)
~/Library/LaunchAgents/com.podcasttranscriber.serve.plist  # generated at install
.env                         # local config (git-ignored); created from .env.template
data/podcast_transcriber.db  # SQLite (WAL) — see docs/architecture.md
```
