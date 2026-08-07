# podcast-transcriber

Spotify episode resolver + job queue + chunked MLX Whisper transcription.

**Phase 1: vertical slice (CLI only).** A Spotify episode URL is resolved to the
publisher's RSS feed (via the iTunes Search API), the exact episode is matched,
and its audio enclosure URL is recovered. A simple SQLite-backed job queue drives
chunked transcription with `mlx-whisper` (Apple Silicon), including per-chunk
checkpoints and resume.

No cloud APIs. No SQLAlchemy (stdlib `sqlite3`). Everything lives under this repo.

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
pt jobs                                                   # list jobs
pt transcribe <job_id> [--model ...] [--chunk-minutes ...]
pt status  [job_id]
pt transcript <job_id> [--json]
pt search "Lex Fridman"
```

`resolve` returns a verification state:

- `VERIFIED` — single, strong match (title + duration agree). Safe to use.
- `REVIEW_REQUIRED` — candidate exists but ambiguous; do **not** auto-trust.
- `UNAVAILABLE` — no feed / no candidate.

> A false match is treated as worse than a failure, so the resolver is
> deliberately conservative: when in doubt it returns `REVIEW_REQUIRED` /
> `UNAVAILABLE` instead of guessing.

To transcribe a real episode's audio you first need the audio file (downloading
audio is not part of this phase). For local files: `pt add-file <path>` registers
the file as an episode and creates a job, then `pt transcribe <job_id>`.

## Data layout

```
data/
├── podcast_transcriber.db        # SQLite (WAL journal)
│    ├── episodes                 # resolved episodes + verification state
│    ├── jobs                     # job queue (one active job at a time)
│    ├── transcripts              # one row per completed job
│    ├── segments                 # per-chunk timed segments
│    └── checkpoints              # per-chunk resume markers
├── audio/                        # (future) downloaded audio
└── cache/
```

Schema migrations are applied on open (`schema_version` table).

## Tests

```bash
.venv/bin/python -m pytest -q     # full suite (one integration test)
.venv/bin/python -m compileall -q src
```

The integration test `tests/test_transcribe_resume.py` generates a ~30&nbsp;s
silence WAV, seeds a completed chunk-0 checkpoint, then runs transcription with
`mlx-community/whisper-tiny` (downloads the model once) and asserts the already
completed chunk is skipped (resume works).

## Roadmap (future phases)

- Audio download + streaming decode from enclosure URLs.
- Owner console / web UI.
- Customer auth, Stripe billing, commission ledger, Twilio + AI receptionist.

## License

MIT.