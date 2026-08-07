"""Integration: end-to-end transcription with a real MLX Whisper model.

- Generates a ~30s silence WAV with the stdlib `wave` module.
- Registers it as an episode and starts a job (chunk_minutes=0.25 -> 2 chunks).
- Pre-seeds a 'done' checkpoint for chunk 0 (simulating an earlier partial run).
- Runs `transcribe_job` against the real mlx-community/whisper-tiny model
  (downloads once via HuggingFace on first run).
- Asserts the completed chunk is SKIPPED (not re-transcribed) and the seeded
  chunk-0 text is preserved, proving resume works.
"""

from __future__ import annotations

import struct
import wave
from pathlib import Path

import pytest

from podcast_transcriber.store import JOB_COMPLETE, Episode, Store
from podcast_transcriber.transcribe import transcribe_job

pytestmark = pytest.mark.integration


def make_silence_wav(path: Path, seconds: float = 30.0, rate: int = 16000) -> Path:
    with wave.open(str(path), "w") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        frames = int(seconds * rate)
        w.writeframes(b"\x00\x00" * frames)
    return path


def test_transcribe_resume_skips_completed_chunk(tmp_path, store: Store):
    wav = make_silence_wav(tmp_path / "silence.wav", seconds=30.0)

    ep = Episode(url=str(wav), title="silence", state="VERIFIED",
                 confidence=1.0, audio_url=str(wav))
    episode_id = store.upsert_episode(ep)
    job = store.create_job(episode_id, model="mlx-community/whisper-tiny",
                           chunk_minutes=0.3)

    # --- seed an already-complete chunk 0 (simulate a prior partial run) ---
    tx_id = store.upsert_transcript(job.id, episode_id, "en")
    store.add_segment(job.id, tx_id, 0, 0.0, 5.0, "SEEDED_CHUNK0_TEXT")
    store.set_checkpoint(job.id, 0, "done", audio_path=str(wav),
                         result={"text": "SEEDED_CHUNK0_TEXT", "segments": 1})

    progress: list[str] = []
    summary = transcribe_job(store, job.id, chunk_minutes=0.3,
                             progress=progress.append)

    # Resumed job must be complete with the seeded chunk skipped.
    assert store.get_job(job.id).status == JOB_COMPLETE
    assert summary["chunks_total"] == 2, summary
    assert summary["chunks_done"] == 2, summary
    assert summary["chunks_skipped"] == 1, summary
    assert any("SKIP" in line for line in progress), progress

    # The seeded chunk-0 content must NOT have been overwritten by re-transcription.
    segs = store.segments_for_job(job.id)
    chunk0_segs = [s for s in segs if s["chunk_index"] == 0]
    assert chunk0_segs, "seeded chunk-0 segment missing"
    assert chunk0_segs[0]["text"] == "SEEDED_CHUNK0_TEXT"
    cp0 = store.get_checkpoint(job.id, 0)
    assert cp0["result"]["text"] == "SEEDED_CHUNK0_TEXT"

    # Chunk 1 (silence) was transcribed by the real model -- checkpoint done.
    cp1 = store.get_checkpoint(job.id, 1)
    assert cp1 is not None and cp1["status"] == "done"