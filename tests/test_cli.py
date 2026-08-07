"""CLI smoke/regression tests.

H1: main(["jobs"]) no longer crashes (function signature mismatch bug).
M7: `transcribe --json` forwards progress to stderr so stdout stays pure JSON.
L8: `resolve --store --json` includes the injected episode_id in the JSON.
Happy paths: add-file, status, transcript, search return 0 without crashing.
"""

from __future__ import annotations

import argparse
import contextlib
import io
import json
import wave
from pathlib import Path

import pytest

from podcast_transcriber import cli
from podcast_transcriber.config import Config
from podcast_transcriber.resolve import Resolution, SpotifyMeta
from podcast_transcriber.store import Episode
from podcast_transcriber.verify import VERIFIED, Candidate, VerificationResult


def _wav(path: Path, seconds: float = 1.0) -> Path:
    with wave.open(str(path), "w") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(16000)
        w.writeframes(b"\x00\x00" * int(seconds * 16000))
    return path


@pytest.fixture(autouse=True)
def _isolate_cfg(monkeypatch, tmp_path):
    monkeypatch.setattr(cli, "get_config", lambda: Config(data_dir=str(tmp_path / "data")))
    yield


@pytest.fixture()
def cfg(tmp_path):
    return Config(data_dir=str(tmp_path / "data"))


def test_main_jobs_no_crash(tmp_path):
    # H1: previously crashed with TypeError (wrong arity).
    assert cli.main(["jobs"]) == 0
    assert cli.main(["status"]) == 0  # no job id -> "no jobs"
    assert cli.main(["search", "nope"]) == 0


def test_main_add_file_jobs_status_transcript(tmp_path):
    wav = _wav(tmp_path / "clip.wav")
    assert cli.main(["add-file", str(wav), "--title", "Clip"]) == 0
    assert cli.main(["jobs"]) == 0
    store = cli.Store(str(cli.get_config().db_path))
    jobs = store.list_jobs()
    job_id = jobs[0].id
    store.close()
    assert cli.main(["status", str(job_id)]) == 0
    assert cli.main(["transcript", str(job_id)]) == 0  # empty transcript path
    assert cli.main(["search", "Clip"]) == 0


def test_cmd_transcribe_json_pure_stdout(monkeypatch, store, cfg):
    # M7: --json must route progress to stderr; stdout must be valid JSON only.
    eid = store.upsert_episode(Episode(url="https://x/e"))
    job = store.create_job(eid)

    def fake_transcribe(store_, job_id, *, model=None, chunk_minutes=None, progress=None):
        progress("chunk 1/1: transcribing with fake")
        return {"job_id": job_id, "model": model, "chunks_done": 1, "segments": 2}

    monkeypatch.setattr(cli, "transcribe_job", fake_transcribe)
    args = argparse.Namespace(job_id=job.id, model=None, chunk_minutes=None, json=True)

    out = io.StringIO()
    err = io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        rc = cli.cmd_transcribe(args, store, None)
    assert rc == 0
    parsed = json.loads(out.getvalue())  # must be pure, parseable JSON
    assert parsed["job_id"] == job.id
    # progress lines went to stderr, not stdout
    assert "transcribing with fake" in err.getvalue()
    assert "transcribing with fake" not in out.getvalue()


def test_resolve_json_store_includes_episode_id(monkeypatch, store, cfg):
    # L8: --json --store must include the episode_id we injected.
    def fake_resolve(url, **kwargs):
        meta = SpotifyMeta(spotify_id="abc", url=url, episode_title="Ep",
                           show_name="Show", duration_seconds=100.0)
        result = VerificationResult(
            state=VERIFIED, confidence=0.95, reason="ok",
            audio_url="http://cdn/x.mp3", matched_title="Ep",
            candidates=[Candidate(audio_url="http://cdn/x.mp3", title="Ep",
                                  confidence=0.95)],
        )
        return Resolution(spotify_id="abc", source_url=url, metadata=meta,
                          feed_url="http://feed", feed_collection="Show", result=result)

    monkeypatch.setattr(cli, "do_resolve", fake_resolve)
    args = argparse.Namespace(spotify_url="https://open.spotify.com/episode/abc",
                              json=True, store=True)

    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        rc = cli.cmd_resolve(args, store, cfg)
    assert rc == 0
    payload = json.loads(out.getvalue())
    assert payload["episode_id"] is not None
    assert store.get_episode(payload["episode_id"]) is not None