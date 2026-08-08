"""Chunked MLX Whisper transcription with per-chunk checkpoints + resume.

Design:
  * Audio is decoded once (mlx_whisper.audio.load_audio -> 16 kHz mono float).
  * The full clip is split into ~10-minute chunks (configurable).
  * Each chunk is transcribed independently; a "checkpoint" row is written to
    SQLite *after* the chunk completes (status='done').
  * On resume, chunks with a 'done' checkpoint are skipped -- nothing is
    re-transcribed.
  * One active job at a time is enforced by the DB (partial unique index on
    jobs.status) and re-checked here before starting.
"""

from __future__ import annotations

import contextlib
import logging
import math
import os
import sqlite3
import sys
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from . import config as config_mod
from .store import JOB_COMPLETE, JOB_FAILED, JOB_PENDING, Store

log = logging.getLogger(__name__)

# Make sure homebrew ffmpeg is findable by mlx_whisper's audio loader.
for _p in ("/opt/homebrew/bin", "/usr/local/bin"):
    if _p not in os.environ.get("PATH", ""):
        os.environ["PATH"] = f"{_p}:{os.environ.get('PATH', '')}"

CHUNK_SECONDS_MIN = 5.0


def _default_transcribe(audio: Any, model: str, **kwargs: Any) -> Dict[str, Any]:
    import mlx_whisper

    return mlx_whisper.transcribe(
        audio, path_or_hf_repo=model, verbose=False, **kwargs
    )


def load_audio_samples(audio_path: str) -> "tuple[Any, float]":
    """Decode audio to (samples, sample_rate) via mlx_whisper's ffmpeg loader."""
    from mlx_whisper.audio import load_audio

    samples = load_audio(audio_path, sr=16000)
    return samples, 16000.0


def plan_chunks(duration_seconds: float, chunk_minutes: float) -> int:
    chunk_seconds = max(chunk_minutes * 60.0, CHUNK_SECONDS_MIN)
    if duration_seconds <= 0:
        return 1
    return max(1, int(math.ceil(duration_seconds / chunk_seconds)))


class TranscribeError(RuntimeError):
    pass


def transcribe_job(
    store: Store,
    job_id: int,
    *,
    model: Optional[str] = None,
    chunk_minutes: Optional[float] = None,
    transcribe_func: Optional[Callable[..., Dict[str, Any]]] = None,
    progress: Optional[Callable[[str], None]] = None,
) -> Dict[str, Any]:
    """Run (or resume) transcription for a job. Returns a summary dict."""
    cfg = config_mod.get_config()

    job = store.get_job(job_id)
    if job is None:
        raise TranscribeError(f"Job {job_id} does not exist")
    # Prefer the caller's value, then the job's original grid (resume), then cfg.
    if chunk_minutes is not None:
        pass
    elif job.chunk_minutes is not None:
        chunk_minutes = job.chunk_minutes
    else:
        chunk_minutes = cfg.chunk_minutes

    transcribe_func = transcribe_func or _default_transcribe
    progress = progress or (lambda s: print(s, file=sys.stdout))

    model = model or job.model or cfg.model
    episode = store.get_episode(job.episode_id)  # type: ignore[arg-type]
    if episode is None or not episode.audio_url:
        raise TranscribeError(f"Job {job_id} has no episode with audio_url")

    audio_path = episode.audio_url
    if audio_path.startswith("file://"):
        audio_path = audio_path[len("file://"):]
    if not Path(audio_path).is_file():
        raise TranscribeError(f"Audio file not found: {audio_path}")

    # --- single-active-job guards ---------------------------------------- #
    # Distinct-job guard: no *other* job may be active (pending/running).
    active = store.active_jobs()
    for other in active:
        if other.id != job_id:
            raise TranscribeError(
                f"Job {other.id} is already {other.status}; "
                "only one active job is allowed at a time"
            )
    # Same-job guard: atomically claim THIS job (PENDING -> RUNNING).  Two
    # processes racing on the same job: only one conditional UPDATE matches, the
    # loser gets rowcount 0 and reports already-running instead of duplicating
    # work.  A partial-unique-index violation means a *different* job grabbed
    # the single active slot between the guard check above and this UPDATE;
    # that is a transient slot race, not a failure -- leave the job PENDING.
    try:
        claimed = store.claim_job(job_id)
    except sqlite3.IntegrityError:
        raise TranscribeError(
            "another job is already active; the single active slot is busy "
            "(will be retried)"
        ) from None
    if not claimed:
        raise TranscribeError(
            f"Job {job_id} is not PENDING; it is already being processed "
            "by another run (resume requires a PENDING job)"
        )

    summary: Dict[str, Any] = {
        "job_id": job_id,
        "model": model,
        "chunk_minutes": chunk_minutes,
        "chunks_total": 0,
        "chunks_done": 0,
        "chunks_skipped": 0,
        "audio": audio_path,
        "segments": 0,
    }

    try:
        samples, sr = load_audio_samples(audio_path)
        duration = float(len(samples)) / float(sr) if sr else 0.0
        n_chunks = plan_chunks(duration, chunk_minutes)
        summary["chunks_total"] = n_chunks
        store.update_job(job_id, chunk_count=n_chunks)

        chunk_seconds = max(chunk_minutes * 60.0, CHUNK_SECONDS_MIN)
        chunk_samples = int(chunk_seconds * sr)
        total_samples = len(samples)

        language: Optional[str] = None
        first_result: Optional[Dict[str, Any]] = None

        for idx in range(n_chunks):
            cp = store.get_checkpoint(job_id, idx)
            if cp and cp["status"] == "done":
                summary["chunks_skipped"] += 1
                summary["chunks_done"] += 1
                progress(f"chunk {idx + 1}/{n_chunks}: SKIP (already done)")
                continue

            start = idx * chunk_samples
            end = min(total_samples, start + chunk_samples)
            progress(f"chunk {idx + 1}/{n_chunks}: transcribing samples "
                     f"[{start // sr:.0f}s..{end // sr:.0f}s] with {model}")
            # Resume idempotency: a chunk that never got its 'done' checkpoint
            # may have left stale segment rows from an earlier partial run.
            # Clear them first so re-transcription cannot duplicate.
            store.delete_segments_for_chunk(job_id, idx)
            try:
                # Some model backends (e.g. mlx_whisper) print diagnostics such
                # as "Detected language: ..." and progress bars straight to
                # stdout. When the CLI runs with --json, that noise would
                # corrupt the pure-JSON summary. Redirect the model call's
                # stdout to stderr so the CLI stdout stays clean.
                with contextlib.redirect_stdout(sys.stderr):
                    result = transcribe_func(samples[start:end], model)
            except Exception as exc:
                store.set_checkpoint(job_id, idx, "failed", audio_path=audio_path)
                raise TranscribeError(f"Chunk {idx} transcription failed: {exc}") from exc

            language = language or result.get("language")
            first_result = first_result or result
            tx_id = store.upsert_transcript(job_id, episode.id or 0, language or "en")

            segments = result.get("segments") or []
            seg_count = 0
            for seg in segments:
                seg_start = float(seg.get("start", 0.0)) + start / sr
                seg_end = float(seg.get("end", 0.0)) + start / sr
                text = (seg.get("text") or "").strip()
                if not text:
                    continue
                store.add_segment(job_id, tx_id, idx, seg_start, seg_end, text)
                seg_count += 1

            store.set_checkpoint(
                job_id,
                idx,
                "done",
                audio_path=audio_path,
                result={"text": result.get("text", ""), "segments": seg_count,
                        "language": language},
            )
            summary["chunks_done"] += 1
            summary["segments"] += seg_count
            progress(f"chunk {idx + 1}/{n_chunks}: done ({seg_count} segments)")

        # Finalize.
        if first_result is None:
            store.upsert_transcript(job_id, episode.id or 0, "en")
        else:
            store.upsert_transcript(
                job_id, episode.id or 0, first_result.get("language") or "en"
            )
        store.update_job(job_id, status=JOB_COMPLETE)
        progress(f"job {job_id} complete: {summary['segments']} segments")
        return summary

    except TranscribeError:
        store.update_job(job_id, status=JOB_FAILED, error=str(sys.exc_info()[1]))
        raise
    except Exception as exc:
        store.update_job(job_id, status=JOB_FAILED, error=str(exc))
        raise TranscribeError(f"Transcription failed: {exc}") from exc