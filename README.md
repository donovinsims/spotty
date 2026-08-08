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

No SQLAlchemy (stdlib `sqlite3`). Everything lives under this repo.

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
| `PT_CHUNK_MINUTES`      | `10`                           | Duration of each transcription chunk          |
| `PT_TOP_RESULTS`        | `25`                           | iTunes Search API result limit                |
| `PT_DURATION_TOLERANCE` | `600` (s)                      | Episodes match duration tolerance             |

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
pt serve [--host 127.0.0.1] [--port 8765]                # Phase 2 web UI
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

> Access from a phone/Tailscale is Phase 3 (the app is mobile-friendly and
> iPhone-ready, but the server currently binds to 127.0.0.1 by default).
> Screenshots: n/a.

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
.venv/bin/python -m pytest -q     # full suite (52 tests: 38 Phase 1 + 14 web)
.venv/bin/python -m compileall -q src
```

The Phase 1 integration test `tests/test_transcribe_resume.py` generates a
~30&nbsp;s silence WAV, seeds a completed chunk-0 checkpoint, then runs
transcription with `mlx-community/whisper-tiny` (downloads the model once) and
asserts the already completed chunk is skipped (resume works). The Phase 2 web
tests (`tests/test_web.py`) run fully offline with injected resolve/download/
transcribe fakes — no network, no model.

## Roadmap (future phases)

- Customer auth, Stripe billing, commission ledger, Twilio + AI receptionist.
- Tailscale/iPhone access (Phase 3), owner console.

## License

MIT.