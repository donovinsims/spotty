# Architecture

podcast-transcriber: Spotify episode resolver + job queue + chunked MLX Whisper
transcription, with a local FastAPI/HTMX web UI (`pt serve`) and a launchd
service (Phase 3) for autostart + iPhone access over Tailscale.

No cloud APIs, no SQLAlchemy — stdlib `sqlite3`, everything runs on one
machine.

---

## Module map

```
src/podcast_transcriber/
├── config.py        Env-driven Config (PT_* vars, .env from repo root)
├── resolve.py       Spotify URL -> publisher RSS feed -> exact episode match
├── download.py      Enclosure download w/ ffprobe decode check, size limit,
│                    SSRF guard (http(s) only), resume/idempotency
├── transcribe.py    Chunked MLX Whisper transcription with per-chunk
│                    checkpoints + resume
├── store.py         sqlite3 store: schema migrations, episodes, jobs,
│                    transcripts, segments, checkpoints; ping()
├── verify.py        Verification-state logic (VERIFIED / REVIEW_REQUIRED /
│                    UNAVAILABLE)
├── cli.py           `pt` console script (Phase 1 commands + `pt serve`)
└── web/
    ├── app.py       FastAPI app factory: routes, error handlers, auth
    │                middleware wiring
    ├── auth.py      Optional single-user auth (PT_AUTH_TOKEN): header /
    │                query / cookie token checks, constant-time compare
    ├── worker.py    One background thread per database; drains QUEUED/
    │                PENDING jobs oldest-first
    ├── templates/   Jinja2 (base, index, jobs, job_detail, transcript,
    │                login, fragments/*)
    └── static/      htmx (vendored), style.css, PWA-lite (manifest, sw.js,
                    icons)
```

### The Phase 1 pipeline (shared by CLI and web)

```
Spotify episode URL
   │  resolve()  — iTunes Search API → feed URL; match title + duration
   ▼
audio enclosure URL  (VERIFIED / REVIEW_REQUIRED / UNAVAILABLE)
   │  download_episode() — stream to data/audio/, ffprobe decode check,
   │                       PT_MAX_DOWNLOAD_BYTES cap, http(s)-only
   ▼
local audio file → job (PENDING)
   │  transcribe_job() — chunk (PT_CHUNK_MINUTES), mlx-whisper per chunk,
   │                     checkpoint + resume
   ▼
transcripts + segments rows
```

Data flow in the web UI: `POST /jobs` → resolve (VERIFIED only) → upsert
episode → `create_job_queued` → worker picks it up → download → transcribe →
status fragment polls until COMPLETE/FAILED.

## Database schema (SQLite, WAL journal)

Applied by versioned migrations on open (`schema_version` table).

| Table          | Purpose                                                        |
|----------------|----------------------------------------------------------------|
| `episodes`     | Resolved episodes: spotify_id, url (UNIQUE), title, show_name, rss_url, audio_url, duration, verification state/confidence/reason/candidates JSON |
| `jobs`         | Queue: episode_id FK, status, model, chunk_minutes, chunk_count, error, created/updated |
| `transcripts`  | One row per completed job: language, segment count (UNIQUE job_id) |
| `segments`     | Per-chunk timed segments: chunk_index, start/end time, text (indexed by job) |
| `checkpoints`  | Per-chunk resume markers: status, audio_path, result (UNIQUE job+chunk) |

### Single-active-job rule (DB-enforced)

```sql
CREATE UNIQUE INDEX ux_jobs_single_active
    ON jobs(status) WHERE status IN ('PENDING', 'RUNNING');
```

At most one job may be PENDING or RUNNING at any time, so a second `POST
/jobs` is stored as `QUEUED` (a status invisible to that index) and the worker
promotes it strictly in creation order — no two transcriptions ever race for
the same model/audio, and no client-side locking is trusted.

## Worker model (web/)

- One `Worker` per database (module-level registry keyed by resolved db path).
- A single daemon thread per database runs the loop:
  `next_queued_job` → promote QUEUED→PENDING (retry on IntegrityError while
  the slot is busy) → `_process` (download + transcribe) → mark FAILED on
  error, leave PENDING when the slot was claimed elsewhere.
- The worker owns its own `sqlite3.Store` created inside its thread (sqlite3
  connections are not thread-safe across threads). FastAPI sync routes each
  get a thread-local Store on the same DB file; WAL allows concurrent readers
  + one writer.
- Crash recovery: on startup a stale-RUNNING sweep marks jobs left RUNNING by
  a killed process back to PENDING so the unique index never deadlocks.
- Shutdown: `stop_worker(db, timeout=PT_WORKER_STOP_TIMEOUT)` — if a job is
  still RUNNING after the timeout it is marked FAILED ("server shutdown") so
  the slot is free on the next boot.

## Web app structure

`create_app(store=, cfg=, resolve_func=, download_func=, transcribe_func=)`
is a factory so tests inject fake resolve/download/transcribe (offline suite)
and a tmp-path store. Lifespan:

1. stale-RUNNING recovery sweep,
2. start the worker,
3. yield (serve),
4. stop the worker with `PT_WORKER_STOP_TIMEOUT`.

### Optional auth (Phase 3)

When `PT_AUTH_TOKEN` is set (via `.env`), an HTTP middleware guards every route
except `/healthz`, `/static/*`, `/login` and `/logout`. Token accepted as:

- `Authorization: Bearer <token>` header (scripts/API),
- `?token=<token>` query parameter,
- `pt_token` cookie (set by the `/login` page, httponly, SameSite=Lax, 30-day).

Comparison is constant-time (`hmac.compare_digest`). Unauthenticated browser
GETs redirect to `/login?next=<path>`; HTMX/API requests get 401 JSON (HTMX
also receives `HX-Redirect: /login`). `PT_AUTH_TOKEN` unset/empty ⇒ auth
disabled, exact Phase 1/2 behaviour. `/healthz` stays public for
`scripts/status.sh`.

## launchd service (Phase 3)

- `deploy/com.podcasttranscriber.serve.plist` is a **template**; `install.sh`
  substitutes `__REPO_DIR__`, `__HOME_DIR__`, `__USER_NAME__` and writes
  `~/Library/LaunchAgents/com.podcasttranscriber.serve.plist`.
- `RunAtLoad=true`; `KeepAlive` restarts on crash/non-zero exit;
  `WorkingDirectory` = repo root; stdout/stderr → `logs/serve.{out,err}.log`.
- **Env handling:** launchd cannot source `.env`, so the plist only sets
  PATH/HOME/USER. `pt serve` → `get_config()` → `config.load_env()` resolves
  `.env` from the repo root (via `Path(__file__).resolve().parents[2]`) then
  the CWD, so all PT_* values come from the repo `.env` — edit `.env` and
  `scripts/restart.sh`, no reinstall needed.
- CLI precedence: `--host/--port` > `PT_HOST/PT_PORT` (.env) >
  `127.0.0.1:8765` defaults.

## Tailscale exposure (Phase 3)

`scripts/tailscale-serve.sh` uses the Tailscale CLI
(`/Applications/Tailscale.app/Contents/MacOS/Tailscale`) to enable
`tailscale serve --bg <PT_PORT>` — an HTTPS proxy of `127.0.0.1:<port>`
reachable only on the tailnet. It checks `serve status --json` first and only
adds an entry for **our** port; other serve entries (e.g. a `:20128` proxy)
are never modified. The printed URL is
`https://<machine>.<tailnet>.ts.net:<port>` (e.g.
`https://donovins-macbook-pro.taila94639.ts.net:8765`). Because `serve`
exposes the app tailnet-wide, the runbook recommends setting `PT_AUTH_TOKEN`.
