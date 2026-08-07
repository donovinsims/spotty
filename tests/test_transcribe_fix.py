"""Focused regression tests for transcription fixes (no real model needed).

M3: two processes/threads racing on the SAME job -- only one may transcribe.
M4: re-transcribing a chunk with stale segments must not duplicate rows.
M5: resume must honour job.chunk_minutes when no value is passed by the caller.
"""

from __future__ import annotations

import json
import threading
import wave
from pathlib import Path

from podcast_transcriber.store import Episode, JOB_COMPLETE, Store
from podcast_transcriber.transcribe import TranscribeError, transcribe_job


def make_silence_wav(path: Path, seconds: float = 6.0, rate: int = 16000) -> Path:
    with wave.open(str(path), "w") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(b"\x00\x00" * int(seconds * rate))
    return path


def fake_result():
    return {
        "language": "en",
        "text": "hello world",
        "segments": [
            {"start": 0.0, "end": 1.0, "text": "hello"},
            {"start": 1.0, "end": 2.0, "text": "world"},
        ],
    }


def _job(store, wav: Path, chunk_minutes=0.05):
    ep = Episode(url=str(wav), title="x", state="VERIFIED",
                 confidence=1.0, audio_url=str(wav))
    eid = store.upsert_episode(ep)
    return eid, store.create_job(eid, chunk_minutes=chunk_minutes)


def test_concurrent_same_job_only_one_runs(tmp_path):
    """Two independent Store connections racing on the same job: exactly one
    wins the claim and transcribes the chunks; the other reports already-running."""
    wav = make_silence_wav(tmp_path / "s.wav", seconds=8.0)
    db = tmp_path / "db.sqlite"
    seed = Store(db)
    eid, job = _job(seed, wav, chunk_minutes=0.05)  # 8s -> 2 chunks
    seed.close()

    calls = 0
    calls_lock = threading.Lock()

    def fake(audio, model):
        nonlocal calls
        with calls_lock:
            calls += 1
        return fake_result()

    barrier = threading.Barrier(2)
    outcomes: list[str] = []

    def worker(stop: threading.Event):
        s = Store(db)  # independent connection, like a separate process
        try:
            barrier.wait(timeout=10)
            transcribe_job(s, job.id, transcribe_func=fake, progress=lambda m: None)
            outcomes.append("completed")
        except TranscribeError as exc:
            outcomes.append(f"already-running:{exc}")
        finally:
            s.close()
            stop.set()

    t1 = threading.Thread(target=worker, args=(threading.Event(),))
    t2 = threading.Thread(target=worker, args=(threading.Event(),))
    for t in (t1, t2):
        t.start()
    for t in (t1, t2):
        t.join(timeout=30)

    # Exactly one thread performed all chunk work (2 chunks = 2 fake calls).
    assert calls == 2, f"expected exactly 1 winner x 2 chunks, got calls={calls}"
    assert any(o == "completed" for o in outcomes), outcomes
    assert any(o.startswith("already-running") for o in outcomes), outcomes


def test_resume_partial_chunk_does_not_duplicate_segments(tmp_path, store):
    """Chunk 0 has a partial run (segments, NO done checkpoint): re-transcription
    must replace rows, never duplicate."""
    wav = make_silence_wav(tmp_path / "p.wav", seconds=6.0)
    eid, job = _job(store, wav, chunk_minutes=0.3)  # 6s/18s -> 1 chunk
    tx = store.upsert_transcript(job.id, eid, "en")
    store.add_segment(job.id, tx, 0, 0.0, 1.0, "STALE_A")
    store.add_segment(job.id, tx, 0, 1.0, 2.0, "STALE_B")
    # NOTE: no set_checkpoint(..., 'done') -> the run looked like a mid-chunk crash.

    summary = transcribe_job(store, job.id, transcribe_func=lambda a, m: fake_result())

    assert store.get_job(job.id).status == JOB_COMPLETE
    segs = store.segments_for_job(job.id)
    assert [s["text"] for s in segs] == ["hello", "world"], segs
    assert store.get_transcript(job.id).segments == 2


def test_resume_uses_stored_chunk_minutes(tmp_path, store):
    wav = make_silence_wav(tmp_path / "m.wav", seconds=6.0)
    _, job = _job(store, wav, chunk_minutes=0.5)
    summary = transcribe_job(store, job.id, transcribe_func=lambda a, m: fake_result())
    # The caller passed no chunk_minutes; the job's stored grid must win.
    assert summary["chunk_minutes"] == 0.5


def test_model_stdout_noise_does_not_leak_into_json_stdout(tmp_path, store, capsys):
    """mlx-whisper prints 'Detected language: ...' directly to stdout. When the
    CLI runs with --json the summary on stdout must remain pure JSON, so
    transcribe_job must redirect model stdout noise away from the CLI's stdout.
    Regression: this test fails before the redirect guard is in place."""
    wav = make_silence_wav(tmp_path / "n.wav", seconds=6.0)
    eid, job = _job(store, wav, chunk_minutes=0.5)  # 6s -> 1 chunk

    # Simulate a model backend that writes noise straight to stdout.
    def noisy_fake(audio, model):
        print("Detected language: English")
        return fake_result()

    summary = transcribe_job(
        store, job.id, transcribe_func=noisy_fake, progress=lambda m: None
    )
    # Mimic the CLI's --json summary emission on stdout.
    print(json.dumps(summary, default=str))

    out = capsys.readouterr().out
    assert "Detected language" not in out
    parsed = json.loads(out)  # stdout is empty modulo pure JSON -> parses cleanly
    assert parsed["job_id"] == job.id