"""Command line interface for podcast-transcriber (Phase 1).

Subcommands:
  resolve  SPOTIFY_URL   Resolve a Spotify episode to an audio URL (network).
  add-file PATH          Register a local audio file as an episode + PENDING job.
  download EPISODE_ID    Fetch an episode's audio enclosure locally + PENDING job.
  jobs                   List jobs.
  transcribe JOB_ID      Transcribe (or resume) a job with MLX Whisper.
  status [JOB_ID]        Show job status and verification info.
  transcript JOB_ID      Print a transcript.
  search QUERY           Search stored episodes.
  serve                  Run the Phase 2 web UI (FastAPI + HTMX).
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import List, Optional

from . import __version__
from .config import get_config
from .download import DownloadError, download_episode
from .resolve import resolve as do_resolve
from .store import (
    JOB_COMPLETE,
    JOB_FAILED,
    JOB_PENDING,
    JOB_RUNNING,
    Episode,
    Store,
    VERIFIED,
)
from .transcribe import TranscribeError, transcribe_job

_STATE_COLORS = {
    VERIFIED: "\033[32mVERIFIED\033[0m",
    "REVIEW_REQUIRED": "\033[33mREVIEW_REQUIRED\033[0m",
    "UNAVAILABLE": "\033[31mUNAVAILABLE\033[0m",
}
_JOB_COLORS = {
    JOB_PENDING: "\033[36mPENDING\033[0m",
    JOB_RUNNING: "\033[33mRUNNING\033[0m",
    JOB_COMPLETE: "\033[32mCOMPLETE\033[0m",
    JOB_FAILED: "\033[31mFAILED\033[0m",
}


def _color(text: str, palette: dict) -> str:
    if not sys.stdout.isatty():
        return text
    return palette.get(text, text)


def _pretty(obj) -> None:
    print(json.dumps(obj, indent=2, default=str))


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="pt", description=__doc__)
    p.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    sub = p.add_subparsers(dest="command", required=True)

    r = sub.add_parser("resolve", help="Resolve a Spotify episode URL to an audio URL")
    r.add_argument("spotify_url")
    r.add_argument("--json", action="store_true", help="print raw JSON")
    r.add_argument("--store", action="store_true", help="persist the episode to the DB")

    af = sub.add_parser("add-file", help="register a local audio file as an episode")
    af.add_argument("path")
    af.add_argument("--title", default=None)
    af.add_argument("--model", default=None)

    d = sub.add_parser("download", help="download an episode's audio enclosure locally + create a job")
    d.add_argument("episode_id", type=int)

    sub.add_parser("jobs", help="list transcription jobs")

    t = sub.add_parser("transcribe", help="transcribe (or resume) a job")
    t.add_argument("job_id", type=int)
    t.add_argument("--model", default=None)
    t.add_argument("--chunk-minutes", type=float, default=None)
    t.add_argument("--json", action="store_true")

    s = sub.add_parser("status", help="show job / episode status")
    s.add_argument("job_id", type=int, nargs="?", default=None)

    tr = sub.add_parser("transcript", help="print the transcript of a job")
    tr.add_argument("job_id", type=int)
    tr.add_argument("--json", action="store_true")

    sr = sub.add_parser("search", help="search episodes")
    sr.add_argument("query")

    sv = sub.add_parser("serve", help="run the Phase 2 web UI (FastAPI + HTMX)")
    sv.add_argument("--host", default=None,
                    help="bind address (default: $PT_HOST or 127.0.0.1)")
    sv.add_argument("--port", type=int, default=None,
                    help="bind port (default: $PT_PORT or 8765)")
    return p


def cmd_resolve(args, store: Store, cfg) -> int:
    try:
        res = do_resolve(args.spotify_url, top_results=cfg.top_results,
                         duration_tolerance=cfg.duration_tolerance)
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    except Exception as exc:  # network failures
        print(f"error: resolve failed: {exc}", file=sys.stderr)
        return 1

    episode_id = None
    if args.store and res.result:
        meta = res.metadata
        ep = Episode(
            spotify_id=res.spotify_id,
            url=res.source_url,
            title=meta.episode_title,
            show_name=meta.show_name,
            rss_url=res.feed_url,
            audio_url=res.result.audio_url,
            duration_seconds=meta.duration_seconds,
            state=res.result.state,
            confidence=res.result.confidence,
            reason=res.result.reason,
            candidates=[c.__dict__ for c in res.result.candidates],
        )
        episode_id = store.upsert_episode(ep)
    try:
        d = res.as_dict()
    except Exception:  # pragma: no cover
        d = {}
    if episode_id and isinstance(d, dict):
        d["episode_id"] = episode_id

    if args.json:
        _pretty(d)
    else:
        st = res.result.state if res.result else "?"
        col = _STATE_COLORS.get(st, st)
        print(f"Spotify episode: {res.spotify_id}")
        print(f"  source URL : {res.source_url}")
        print(f"  episode    : {res.metadata.episode_title or '?'}")
        print(f"  show       : {res.metadata.show_name or '?'}")
        if res.metadata.duration_seconds:
            print(f"  duration   : {res.metadata.duration_seconds:.0f}s (Spotify)")
        print(f"  feed URL   : {res.feed_url or '?'}  ({res.feed_collection or '?'})")
        if res.result:
            print(f"  state      : {col}")
            print(f"  confidence : {res.result.confidence:.3f}")
            print(f"  reason     : {res.result.reason}")
            if res.result.audio_url:
                print(f"  audio URL  : {res.result.audio_url}")
            if res.result.candidates:
                print("  candidates :")
                for c in res.result.candidates:
                    print(f"    - {c.title!r} conf={c.confidence:.2f} dur={c.duration_seconds or '?'}")
                if st in ("REVIEW_REQUIRED", "UNAVAILABLE"):
                    print("  NOTE: ambiguous; review candidates manually (false match > failure).")
        if episode_id:
            print(f"  stored as  : episode id {episode_id}")
    return 0


def cmd_add_file(args, store: Store, cfg) -> int:
    path = str(Path(args.path).resolve())
    if not Path(path).is_file():
        print(f"error: file not found: {path}", file=sys.stderr)
        return 2
    title = args.title or Path(path).name
    ep = Episode(
        url=path,
        title=title,
        state=VERIFIED,
        confidence=1.0,
        reason="Local audio file registered directly as the episode source.",
        audio_url=path,
    )
    episode_id = store.upsert_episode(ep)
    job = store.create_job(episode_id, model=args.model, chunk_minutes=None)
    print(f"registered episode {episode_id}: {title}")
    print(f"created job {job.id} ({JOB_PENDING})")
    return 0


def cmd_download(args, store: Store, cfg) -> int:
    try:
        out = download_episode(
            store, args.episode_id, cfg.audio_dir,
            progress=lambda s: print(s, file=sys.stderr),
        )
    except (DownloadError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    print(f"audio for episode {out['episode_id']}: {out['audio_path']}")
    print(f"job {out['job'].id} ({out['job'].status})")
    print(f"next: pt transcribe {out['job'].id}")
    return 0


def cmd_jobs(store: Store, cfg) -> int:
    jobs = store.list_jobs(limit=50)
    if not jobs:
        print("no jobs")
        return 0
    for j in jobs:
        core = _JOB_COLORS.get(j.status, j.status)
        print(f"job {j.id}: {core} model={j.model or cfg.model} chunks={j.chunk_count} "
              f"episode={j.episode_id}")
    return 0


def cmd_transcribe(args, store: Store, cfg) -> int:
    try:
        summary = transcribe_job(
            store, args.job_id, model=args.model,
            chunk_minutes=args.chunk_minutes,
            progress=(lambda s: print(s, file=sys.stderr)) if args.json else None,
        )
    except (TranscribeError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    if args.json:
        print(json.dumps(summary, indent=2, default=str))
    return 0


def cmd_status(args, store: Store, cfg) -> int:
    if args.job_id is not None:
        job = store.get_job(args.job_id)
        if job is None:
            print(f"error: job {args.job_id} not found", file=sys.stderr)
            return 1
        ep = store.get_episode(job.episode_id or 0)
        tx = store.get_transcript(job.id or 0)
        col = _JOB_COLORS.get(job.status, job.status)
        print(f"job {job.id}: {col}")
        if job.model:
            print(f"  model   : {job.model}")
        print(f"  chunks  : {job.chunk_count or 0}")
        print(f"  episode : {ep.title if ep else '?'}")
        if ep:
            print(f"    state       : {_STATE_COLORS.get(ep.state, ep.state)}")
            print(f"    confidence  : {ep.confidence}")
            print(f"    episode     : {ep.title}")
            print(f"    audio_url   : {ep.audio_url}")
        if tx:
            segs = store.segments_for_job(job.id)
            print(f"  transcript: {len(segs)} segments, language={tx.language}")
        if job.error:
            print(f"  error   : {job.error}")
        return 0
    # no job id: show most recent by status
    jobs = store.list_jobs(limit=1)
    if not jobs:
        print("no jobs")
        return 0
    return cmd_status(argparse.Namespace(job_id=jobs[0].id, **vars(args)), store, cfg)


def cmd_transcript(args, store: Store, cfg) -> int:
    segs = store.segments_for_job(args.job_id)
    if not segs:
        print(f"no transcript for job {args.job_id}")
        return 0
    if args.json:
        print(json.dumps(segs, indent=2, default=str))
        return 0
    print(f"# transcript for job {args.job_id}")
    for s in segs:
        print(f"[{s['start_time']:7.1f} -> {s['end_time']:7.1f}] {s['text']}")
    return 0


def cmd_search(args, store: Store, cfg) -> int:
    eps = store.find_episodes(args.query)
    if not eps:
        print("no matches")
        return 0
    for ep in eps:
        print(f"episode {ep.id}: {ep.title} | {ep.show_name} | {_STATE_COLORS.get(ep.state, ep.state)}")
    return 0


def cmd_serve(args, store: Store, cfg) -> int:
    import uvicorn

    from .web import create_app

    cfg.ensure_dirs()
    app = create_app(store=store, cfg=cfg)
    # --host/--port (when given) win over $PT_HOST/$PT_PORT (.env), which in
    # turn win over the 127.0.0.1:8765 defaults.
    host = args.host or cfg.host
    port = args.port or cfg.port
    print(f"podcast-transcriber web UI on http://{host}:{port} "
          f"(data dir: {cfg.data_dir})", file=sys.stderr)
    uvicorn.run(app, host=host, port=port, log_level="info")
    return 0


def main(argv: Optional[List[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    cfg = get_config()
    cfg.ensure_dirs()
    store = Store(str(cfg.db_path))
    try:
        if args.command == "resolve":
            return cmd_resolve(args, store, cfg)
        if args.command == "add-file":
            return cmd_add_file(args, store, cfg)
        if args.command == "download":
            return cmd_download(args, store, cfg)
        if args.command == "jobs":
            return cmd_jobs(store, cfg)
        if args.command == "transcribe":
            return cmd_transcribe(args, store, cfg)
        if args.command == "status":
            return cmd_status(args, store, cfg)
        if args.command == "transcript":
            return cmd_transcript(args, store, cfg)
        if args.command == "search":
            return cmd_search(args, store, cfg)
        if args.command == "serve":
            return cmd_serve(args, store, cfg)
        return 0
    finally:
        store.close()


if __name__ == "__main__":
    raise SystemExit(main())