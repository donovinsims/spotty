# podcast-transcriber

Spotify episode resolver + job queue + chunked MLX Whisper transcription.

**Phase 1: vertical slice (CLI only).** A Spotify episode URL is resolved to the
publisher's RSS feed (via the iTunes Search API), the exact episode is matched,
and its audio enclosure URL is recovered. A simple SQLite-backed job queue drives
chunked transcription with `mlx-whisper` (Apple Silicon), including per-chunk
checkpoints and resume.

**Phase 2: local web UI.** A FastAPI + Jinja2/HTMX web app (`pt serve`) drives
the exact same Phase 1 pipeline — resolve, download, transcribe — with live
job progress, a readable transcript with search, plain-text/SRT downloads,
global episode search, and PWA-lite (offline app shell). No cloud APIs, no
external CDNs; everything runs on this machine.

**Phase 3: deployment & operations.** `scripts/install.sh` installs a launchd
auto-start service (`com.podcasttranscriber.serve`) with KeepAlive, a
repo-root `.env.template`, `GET /healthz` liveness + DB probe, optional
single-user auth (`PT_AUTH_TOKEN`, Bearer header / login cookie),
and `scripts/tailscale-serve.sh` for iPhone access over Tailscale. See
[`docs/deployment-runbook.md`](docs/deployment-runbook.md),
[`docs/rollback.md`](docs/rollback.md) and
[`docs/architecture.md`](docs/architecture.md).

**Phase 4: hardening & final polish.** A per-IP rate limit on `POST /jobs`
(`PT_RATE_LIMIT_PER_MIN`, 429 + Retry-After) and a queue cap
(`PT_MAX_QUEUED`, 409 "too many jobs queued") keep the single-worker service
stable; the auth cookie gets the `Secure` flag when the app is bound to a
non-loopback interface (and a startup warning when auth is off on an exposed
host); `pt doctor` runs a battery of preflight checks (ffmpeg, disk, DB,
worker state, Tailscale, launchd, model cache); the UI gets iPhone-focused
CSS polish plus a visible no-auth hint; and
[`docs/iphone-test-plan.md`](docs/iphone-test-plan.md) is a manual end-to-end
checklist for the phone.

No SQLAlchemy (stdlib `sqlite3`). Everything lives under this repo.

## What's where

```
src/podcast_transcriber/
├── config.py        PT_* env config (.env from repo root), loopback helper
├── resolve.py       Spotify URL -> publisher RSS feed -> exact episode match
├── download.py      Enclosure download w/ ffprobe decode check, size/SSRF guards
├── transcribe.py    Chunked MLX Whisper transcription, checkpoints + resume
├── store.py         sqlite3 store (WAL): episodes, jobs, transcripts, segments,
│                    checkpoints; schema migrations; queued-job counts
├── verify.py        Verification states (VERIFIED / REVIEW_REQUIRED / UNAVAILABLE)
├── doctor.py        `pt doctor` preflight checks (Phase 4)
├── cli.py           `pt` console script (Phase 1 commands + `pt serve` + doctor)
└── web/
    ├── app.py       FastAPI app factory: routes, error handlers, auth wiring,
    │                rate limiter + queue cap (Phase 4)
    ├── auth.py      Optional token auth (PT_AUTH_TOKEN): Bearer header / cookie
    ├── ratelimit.py Per-IP sliding-window limiter (stdlib, Phase 4)
    ├── worker.py    One background thread per database; drains QUEUED/PENDING
    ├── templates/   Jinja2 (base, index, jobs, job_detail, transcript, login, fragments/*)
    └── static/      htmx (vendored), style.css, PWA-lite (manifest, sw.js, icons)

scripts/             install/start/stop/restart/status/logs/uninstall/tailscale-serve
deploy/              launchd plist TEMPLATE (paths baked at install time)
docs/                architecture, deployment runbook, rollback, iPhone test plan
data/                SQLite DB, downloaded audio, model cache (git-ignored)
```

## Requirements

- macOS on Apple Silicon (arm64)
- `ffmpeg` + `ffprobe` on `PATH` (e.g. `/opt/homebrew/bin`)
- Python ≥ 3.10

## Install

```bash
python -m venv .venv
.venv/bin/pip install -e .[dev]     # or: -e .  (production)
```

This installs the `pt` console script and the `podcast_transcriber` package.

## Configuration (`.env` / environment variables)

Create a `.env` in the repo root (it is git-ignored) or export env vars.

> `.env` is resolved from the **repo root** first, then the current working
> directory, so `pt` works from any CWD — no need to `cd` into the repo.

| Variable                | Default                        | Description                                   |
|-------------------------|--------------------------------|-----------------------------------------------|
| `PT_MODEL`              | `mlx-community/whisper-small-mlx` | MLX Whisper model for transcription           |
| `PT_DATA_DIR`           | `data/`                        | Data directory (DB, audio, cache)             |
| `PT_HOST`               | `127.0.0.1`                    | `pt serve` bind address                       |
| `PT_PORT`               | `8765`                         | `pt serve` port                               |
| `PT_AUTH_TOKEN`         | *(empty)*                      | Single-user auth token; empty = no auth       |
| `PT_MAX_DOWNLOAD_BYTES` | `1073741824` (1 GiB)           | Max bytes accepted per audio download         |
| `PT_WORKER_STOP_TIMEOUT`| `5` (s)                        | Worker stop timeout before failing a job      |
| `PT_RATE_LIMIT_PER_MIN` | `10`                           | Max `POST /jobs` per client IP per minute (429 + Retry-After) |
| `PT_MAX_QUEUED`         | `50`                           | Max PENDING+QUEUED jobs before new submissions are rejected (409) |
| `PT_TRUST_PROXY`        | `false`                        | Trust `X-Forwarded-For` for rate limiting (only behind your own proxy) |
| `PT_CHUNK_MINUTES`      | `10`                           | Duration of each transcription chunk          |
| `PT_TOP_RESULTS`        | `25`                           | iTunes Search API result limit                |
| `PT_DURATION_TOLERANCE` | `600` (s)                      | Episodes match duration tolerance             |

`--host`/`--port` on `pt serve` override `PT_HOST`/`PT_PORT`, which override
the defaults. See `.env.template` for the full commented list.

The MLX model downloads on first use into HuggingFace's cache
(`~/.cache/huggingface`), so the first transcription needs network.

## CLI usage

```
pt resolve  "https://open.spotify.com/episode/<id>"     # resolve URL -> audio
pt resolve  "https://open.spotify.com/episode/<id>" --store
pt add-file /path/to/audio.wav [--title "My clip"]       # register local audio
pt download <episode_id>                                 # fetch remote audio + create a job
pt jobs                                                   # list jobs
pt transcribe <job_id> [--model ...] [--chunk-minutes ...]
pt status  [job_id]
pt transcript <job_id> [--json]
pt search "Lex Fridman"
pt serve [--host 127.0.0.1] [--port 8765]                # web UI ($PT_HOST/$PT_PORT)
pt doctor                                                # preflight health checks (Phase 4)
```

`resolve` returns a verification state:

- `VERIFIED` — single, strong match (title + duration agree). Safe to use.
- `REVIEW_REQUIRED` — candidate exists but ambiguous; do **not** auto-trust.
- `UNAVAILABLE` — no feed / no candidate.

> A false match is treated as worse than a failure, so the resolver is
> deliberately conservative: when in doubt it returns `REVIEW_REQUIRED` /
> `UNAVAILABLE` instead of guessing.

To transcribe a real episode's audio, the natural three-step flow is:

```bash
pt resolve  "https://open.spotify.com/episode/<id>" --store   # 1. verify + find enclosure
pt download <episode_id>                                       # 2. fetch audio locally (creates a job)
pt transcribe <job_id>                                         # 3. chunked transcription (resumable)
```

`pt download <episode_id>` streams the enclosure URL into `data/audio/`
(verifying it decodes via `ffprobe`, and rejecting non-http(s) schemes), updates
the episode's `audio_url` to the local path, and creates a `PENDING` job if the
episode has none yet. If the audio URL is already a local path, the download is
skipped. For local files you can instead use `pt add-file <path>`, which
registers the file and creates a job in one step.

## Web UI (Phase 2)

```bash
.venv/bin/pt serve                    # http://127.0.0.1:8765
.venv/bin/pt serve --host 0.0.0.0 --port 9000
```

Open http://127.0.0.1:8765, paste a Spotify episode URL, and watch the job
progress live (HTMX polling every 2s while PENDING/RUNNING, stopping at
COMPLETE/FAILED). When done, view the transcript with timestamps, search it
with highlighted matches, and download it as `.txt` or `.srt`. The home page
also has a global episode search. The app is PWA-lite: an installable
manifest, a service worker that caches the app shell for offline start, and
local icons — no external CDNs (htmx is vendored under
`src/podcast_transcriber/web/static/`).

How it works:

- `POST /jobs` resolves the URL with the same `resolve()` as `pt resolve
  --store`. Only `VERIFIED` episodes get a job; `REVIEW_REQUIRED` /
  `UNAVAILABLE` return the candidates for manual review and create nothing.
- An in-process worker thread (one per database) picks waiting jobs
  oldest-first and runs the same `download_episode()` + `transcribe_job()` as
  the CLI. The Phase 1 single-active-job rule holds: at most one job is
  RUNNING at a time (DB-enforced), and a second `POST /jobs` simply waits —
  jobs stay PENDING (or QUEUED while the slot is momentarily taken) until the
  active job finishes.

### Optional auth (`PT_AUTH_TOKEN`)

When `PT_AUTH_TOKEN` is set in `.env`, every route except `/healthz`,
`/static/*`, `/sw.js`, `/manifest.webmanifest`, `/login` and `/logout` requires
the token, accepted as `Authorization: Bearer <token>` or the `pt_token`
cookie set by the `/login` page (unauthenticated browser GETs redirect to
`/login`, API calls get 401 JSON; comparison is constant-time). Query-string
`?token=` is **not** accepted — it would leak the credential into uvicorn
access logs. Empty/unset ⇒ no auth (current single-user behaviour). Generate
one with `openssl rand -hex 32`.

The `pt_token` cookie is `HttpOnly`, `SameSite=Lax`, 30-day, and marked
`Secure` whenever the app is bound to a **non-loopback** interface (e.g.
`--host 0.0.0.0`); on loopback hosts it stays unencrypted-friendly for plain
HTTP local use. When auth is off and the app is bound to a non-loopback
interface, `pt serve` logs a prominent startup warning and the home page shows
a "No auth" banner.

## Diagnostics: `pt doctor` (Phase 4)

```bash
.venv/bin/pt doctor
```

Runs local preflight checks and prints `[PASS]`/`[WARN]`/`[FAIL]` lines:
Python/venv + `mlx_whisper`, `ffmpeg`/`ffprobe`, data-dir writability + ≥ 1 GiB
free disk, which `PT_*` vars are set (secrets masked), the SQLite DB (schema
version, episode/job counts), worker state (RUNNING / PENDING / QUEUED +
stale-RUNNING hint), Tailscale (node up + our `serve` entry for `PT_PORT`),
the launchd service, and the model-cache size. Exit code is `0` when nothing
FAILs, `1` when any check FAILs (WARNs never fail the run). See the runbook
§7 for what each line means.

## Operations (Phase 3)

```bash
scripts/install.sh      # create .env if missing, install launchd autostart, start
scripts/status.sh       # launchd state + GET /healthz probe
scripts/start.sh        # start the service
scripts/stop.sh         # stop the service (unloads the job from launchd;
                        # plist FILE kept, autostart suspended until start/install)
scripts/restart.sh      # stop + start (after .env edits or upgrades)
scripts/logs.sh         # tail logs/
scripts/uninstall.sh    # stop + unload + remove the plist
scripts/tailscale-serve.sh   # idempotent iPhone access over Tailscale (HTTPS)
```

- `pt serve` runs as a launchd agent (`com.podcasttranscriber.serve`),
  auto-starts at login, and is restarted by launchd on crash. It loads the
  repo `.env` itself, so no PT_* values are baked into the plist — edit `.env`
  and `scripts/restart.sh`.
- `GET /healthz` (always public) returns
  `{"status":"ok","version":"0.1.0","db":"ok"}` and is used by
  `scripts/status.sh`.
- `scripts/tailscale-serve.sh` enables
  `tailscale serve --yes --bg --https=8765 http://127.0.0.1:8765` (HTTPS
  proxy of `127.0.0.1:8765` bound to our own https port, tailnet-only) and
  prints the iPhone URL, e.g.
  `https://donovins-macbook-pro.taila94639.ts.net:8765`. It never touches
  other serve entries (e.g. the existing `:20128` proxy).
- Full runbook: [`docs/deployment-runbook.md`](docs/deployment-runbook.md);
  rollback: [`docs/rollback.md`](docs/rollback.md); architecture:
  [`docs/architecture.md`](docs/architecture.md).

> Tailscale `serve` exposes the UI to every device on the tailnet — set
> `PT_AUTH_TOKEN` first; the iPhone signs in with that token.

## Data layout

```
data/
├── podcast_transcriber.db        # SQLite (WAL journal)
│    ├── episodes                 # resolved episodes + verification state
│    ├── jobs                     # job queue (one active job at a time)
│    ├── transcripts              # one row per completed job
│    ├── segments                 # per-chunk timed segments
│    └── checkpoints              # per-chunk resume markers
├── audio/                        # downloaded episode audio (pt download)
└── cache/
```

Schema migrations are applied on open (`schema_version` table).

## Tests

```bash
.venv/bin/python -m pytest -q     # full suite (131 tests: Phase 1/2/3 + auth + Phase 4 hardening)
.venv/bin/python -m compileall -q src
```

The Phase 1 integration test `tests/test_transcribe_resume.py` generates a
~30&nbsp;s silence WAV, seeds a completed chunk-0 checkpoint, then runs
transcription with `mlx-community/whisper-tiny` (downloads the model once) and
asserts the already completed chunk is skipped (resume works). The Phase 2 web
tests (`tests/test_web.py`), Phase 3 auth tests (`tests/test_auth.py`), the
Phase 4 rate-limit/queue-cap tests (`tests/test_ratelimit.py`) and the doctor
tests (`tests/test_doctor.py`) run fully offline with injected
resolve/download/transcribe fakes — no network, no model, no launchd, no
tailscale.

## Roadmap (future phases)

- Owner console, multi-salon multi-tenancy.
- Customer auth, Stripe billing, commission ledger, Twilio + AI receptionist.

## License

MIT.