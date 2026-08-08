"""Phase 2 web UI tests (FastAPI TestClient).

Everything is fully offline: resolve/download/transcribe are injected fakes,
so no network requests and no MLX model runs.  The in-process worker runs in a
background thread against a tmp-path SQLite database.
"""

from __future__ import annotations

import re
import threading
import time
import wave
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from podcast_transcriber.config import Config
from podcast_transcriber.resolve import Resolution, SpotifyMeta
from podcast_transcriber.store import (
    JOB_COMPLETE,
    JOB_FAILED,
    JOB_PENDING,
    JOB_QUEUED,
    JOB_RUNNING,
    Episode,
    Store,
)
from podcast_transcriber.transcribe import TranscribeError
from podcast_transcriber.verify import (
    REVIEW_REQUIRED,
    UNAVAILABLE,
    VERIFIED,
    Candidate,
    VerificationResult,
)
from podcast_transcriber.web import create_app

URL1 = "https://open.spotify.com/episode/aaaaaaaaaa"
URL2 = "https://open.spotify.com/episode/bbbbbbbbbb"
EP1 = "My Test Episode"
EP2 = "Another Test Episode"


def make_wav(path: Path, seconds: float = 1.0) -> Path:
    with wave.open(str(path), "w") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(16000)
        w.writeframes(b"\x00\x00" * int(seconds * 16000))
    return path


def resolution(url: str, *, state: str = VERIFIED, title: str = EP1,
               show: str = "Test Show") -> Resolution:
    audio = "https://cdn.example.test/ep.mp3" if state == VERIFIED else None
    candidates = [Candidate(audio_url=audio, title=title, confidence=0.97)] \
        if state == VERIFIED else []
    if state == REVIEW_REQUIRED:
        candidates = [
            Candidate(audio_url="https://cdn.example.test/a.mp3", title="Ambiguous A", confidence=0.7),
            Candidate(audio_url="https://cdn.example.test/b.mp3", title="Ambiguous B", confidence=0.6),
        ]
    meta = SpotifyMeta(spotify_id="abc", url=url, episode_title=title,
                       show_name=show, duration_seconds=120.0)
    result = VerificationResult(
        state=state,
        confidence=0.97 if state == VERIFIED else 0.7,
        reason="ok" if state == VERIFIED else "ambiguous match",
        audio_url=audio,
        matched_title=title,
        candidates=candidates,
    )
    return Resolution(spotify_id="abc", source_url=url, metadata=meta,
                      feed_url="https://feed.example.test/rss", result=result)


def fake_resolve(url: str, **kwargs) -> Resolution:
    if "spotify.com/episode" not in url:
        raise ValueError(f"Not a Spotify episode URL: {url!r}")
    return resolution(url)


def fake_download(store, episode_id, audio_dir, *, progress=None, **kwargs):
    ep = store.get_episode(episode_id)
    assert ep is not None, "download called for missing episode"
    if progress:
        progress("downloaded (mock)")
    job = next((j for j in store.list_jobs() if j.episode_id == episode_id), None)
    if job is None:
        job = store.create_job(episode_id)
    return {"episode_id": episode_id, "audio_path": ep.audio_url,
            "duration": 1.0, "job": job}


def fake_transcribe(store, job_id, *, model=None, chunk_minutes=None, progress=None):
    """Mimic transcribe_job's contract: claim -> segments -> COMPLETE."""
    if not store.claim_job(job_id):
        raise TranscribeError(f"job {job_id} not pending")
    store.update_job(job_id, chunk_count=1)
    job = store.get_job(job_id)
    episode = store.get_episode(job.episode_id)
    tx = store.upsert_transcript(job_id, episode.id, "en")
    store.add_segment(job_id, tx, 0, 0.0, 4.0,
                      "Hello world this is a test podcast.")
    store.add_segment(job_id, tx, 0, 4.0, 8.0,
                      "We talk about open source software and sailing.")
    store.update_job(job_id, status=JOB_COMPLETE)
    if progress:
        progress("complete (mock)")
    return {"job_id": job_id, "segments": 2, "chunks_done": 1}


def wait_for(store, job_id: int, status: str, timeout: float = 8.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        job = store.get_job(job_id)
        if job is not None and job.status == status:
            return job
        time.sleep(0.05)
    raise AssertionError(
        f"job {job_id} did not reach {status}; got "
        f"{store.get_job(job_id).status if store.get_job(job_id) else None}"
    )


def make_app(store, tmp_path, **overrides):
    cfg = Config(data_dir=str(tmp_path / "data"))
    kwargs = dict(
        resolve_func=fake_resolve,
        download_func=fake_download,
        transcribe_func=fake_transcribe,
    )
    kwargs.update(overrides)
    return create_app(store=store, cfg=cfg, **kwargs)


# --------------------------------------------------------------------------- #
# pages
# --------------------------------------------------------------------------- #
def test_index_page_renders(store, tmp_path):
    with TestClient(make_app(store, tmp_path)) as client:
        r = client.get("/")
    assert r.status_code == 200
    assert "Spotify episode URL" in r.text
    assert 'hx-post="/jobs"' in r.text
    assert "Search stored episodes" in r.text


def test_jobs_list_page(store, tmp_path):
    eid = store.upsert_episode(Episode(url=URL1, title=EP1, state=VERIFIED))
    store.create_job(eid)
    with TestClient(make_app(store, tmp_path)) as client:
        r = client.get("/jobs")
    assert r.status_code == 200
    assert EP1 in r.text
    assert f"#1" in r.text


def test_jobs_list_ordered_newest_first(store, tmp_path):
    for url, title in ((URL1, EP1), (URL2, EP2)):
        eid = store.upsert_episode(Episode(url=url, title=title, state=VERIFIED))
        job = store.create_job(eid)
        store.update_job(job.id, status=JOB_COMPLETE)  # free the single slot
    with TestClient(make_app(store, tmp_path)) as client:
        r = client.get("/jobs")
    ids = [int(m) for m in re.findall(r"/jobs/(\d+)\">#", r.text)]
    assert ids == [2, 1], ids


def test_job_detail_page_renders(store, tmp_path):
    eid = store.upsert_episode(Episode(
        url=URL1, title=EP1, show_name="Test Show", state=VERIFIED,
        confidence=0.97, reason="ok",
    ))
    job = store.create_job(eid)
    with TestClient(make_app(store, tmp_path)) as client:
        r = client.get(f"/jobs/{job.id}")
    assert r.status_code == 200
    assert EP1 in r.text
    assert "Test Show" in r.text
    assert "VERIFIED" in r.text
    assert "0.970" in r.text
    assert f'hx-get="/jobs/{job.id}/status"' in r.text  # polling wired up


def test_job_detail_404(store, tmp_path):
    with TestClient(make_app(store, tmp_path)) as client:
        r = client.get("/jobs/9999")
    assert r.status_code == 404
    assert "not found" in r.text


# --------------------------------------------------------------------------- #
# POST /jobs
# --------------------------------------------------------------------------- #
def test_post_jobs_happy_path_runs_worker(store, tmp_path):
    """VERIFIED resolve -> job created -> worker downloads + transcribes ->
    job COMPLETE -> transcript/search/download all work."""
    wav = make_wav(tmp_path / "clip.wav")
    ver_resolution = resolution(URL1)
    ver_resolution.result.audio_url = str(wav)

    def local_resolve(url, **kwargs):
        return ver_resolution

    with TestClient(make_app(store, tmp_path, resolve_func=local_resolve)) as client:
        r = client.post("/jobs", data={"url": URL1})
        assert r.status_code == 200
        assert r.headers.get("HX-Redirect") is not None
        job_id = int(r.headers["HX-Redirect"].split("/")[-1])
        assert EP1 in r.text  # job detail page returned

        wait_for(store, job_id, JOB_COMPLETE)
        job = store.get_job(job_id)
        assert job.status == JOB_COMPLETE
        assert job.chunk_count == 1

        # job detail page reflects completion + stops polling
        detail = client.get(f"/jobs/{job_id}")
        assert "COMPLETE" in detail.text
        assert "View transcript" in detail.text
        assert f'hx-get="/jobs/{job_id}/status"' not in detail.text

        # transcript page
        tx = client.get(f"/jobs/{job_id}/transcript")
        assert tx.status_code == 200
        assert "Hello world this is a test podcast." in tx.text
        assert "00:00" in tx.text

        # download .txt
        dl = client.get(f"/jobs/{job_id}/transcript/download")
        assert dl.status_code == 200
        assert dl.headers["content-type"].startswith("text/plain")
        assert "transcript-" in dl.headers["content-disposition"]
        assert "[00:00:00] Hello world this is a test podcast." in dl.text
        assert "Title: My Test Episode" in dl.text

        # download .srt
        srt = client.get(f"/jobs/{job_id}/transcript/srt")
        assert srt.status_code == 200
        assert "-->" in srt.text
        assert "00:00:04,000" in srt.text

        # search within transcript highlights matches
        sr = client.post(f"/jobs/{job_id}/transcript/search", data={"q": "software"})
        assert sr.status_code == 200
        assert "<mark>software</mark>" in sr.text
        assert "matching segment" in sr.text
        sr0 = client.post(f"/jobs/{job_id}/transcript/search", data={"q": "zzz"})
        assert "No matches" in sr0.text


def test_post_jobs_review_required_creates_no_job(store, tmp_path):
    def local_resolve(url, **kwargs):
        return resolution(url, state=REVIEW_REQUIRED)

    with TestClient(make_app(store, tmp_path, resolve_func=local_resolve)) as client:
        r = client.post("/jobs", data={"url": URL1})
    assert r.status_code == 200
    assert "Manual review required" in r.text
    assert "Ambiguous A" in r.text  # candidates surfaced
    assert "no job created" in r.text
    assert store.list_jobs() == []
    assert store.find_episodes("My Test") == []


def test_post_jobs_unavailable_creates_no_job(store, tmp_path):
    def local_resolve(url, **kwargs):
        return resolution(url, state=UNAVAILABLE)

    with TestClient(make_app(store, tmp_path, resolve_func=local_resolve)) as client:
        r = client.post("/jobs", data={"url": URL1})
    assert r.status_code == 200
    assert "Episode unavailable" in r.text
    assert store.list_jobs() == []


def test_post_jobs_invalid_url_shows_error(store, tmp_path):
    with TestClient(make_app(store, tmp_path)) as client:
        r = client.post("/jobs", data={"url": "https://example.com/not-a-podcast"})
    assert r.status_code == 200
    assert "Not a Spotify episode URL" in r.text
    assert store.list_jobs() == []


# --------------------------------------------------------------------------- #
# status fragment
# --------------------------------------------------------------------------- #
def test_status_fragment_shows_progress(store, tmp_path):
    eid = store.upsert_episode(Episode(url=URL1, title=EP1))
    job = store.create_job(eid)
    store.update_job(job.id, status=JOB_RUNNING, chunk_count=4)
    store.set_checkpoint(job.id, 0, "done")
    store.set_checkpoint(job.id, 1, "done")
    with TestClient(make_app(store, tmp_path)) as client:
        r = client.get(f"/jobs/{job.id}/status")
    assert r.status_code == 200
    assert "RUNNING" in r.text
    assert "2 / 4" in r.text
    assert 'style="width: 50%"' in r.text
    assert 'hx-trigger="every 2s"' in r.text  # keeps polling


def test_status_fragment_terminal_stops_polling(store, tmp_path):
    eid = store.upsert_episode(Episode(url=URL1, title=EP1))
    job = store.create_job(eid)
    store.update_job(job.id, status=JOB_FAILED, error="boom")
    with TestClient(make_app(store, tmp_path)) as client:
        r = client.get(f"/jobs/{job.id}/status")
    assert r.status_code == 200
    assert "FAILED" in r.text
    assert "boom" in r.text
    assert 'hx-trigger="every 2s"' not in r.text  # polling stopped


# --------------------------------------------------------------------------- #
# single-active-job via the web worker
# --------------------------------------------------------------------------- #
def test_second_job_stays_queued_until_first_finishes(store, tmp_path):
    """Two POST /jobs quickly: the second job waits (PENDING or QUEUED) and
    only runs after the first completes -- single-active-job holds."""
    first_entered = threading.Event()
    release = threading.Event()
    calls: list = []

    def slow_transcribe(store_, job_id, *, model=None, chunk_minutes=None, progress=None):
        # Mirror transcribe_job's guard: refuse to start while another job is
        # active, leaving this one PENDING for a later retry.
        for other in store_.active_jobs():
            if other.id != job_id:
                raise TranscribeError(f"job {other.id} is already active")
        assert store_.claim_job(job_id), "slow transcribe must win the claim"
        calls.append(job_id)
        if len(calls) == 1:
            first_entered.set()
            release.wait(10)
        store_.update_job(job_id, chunk_count=1)
        store_.update_job(job_id, status=JOB_COMPLETE)
        if progress:
            progress("complete (mock)")
        return {"job_id": job_id}

    with TestClient(make_app(store, tmp_path, transcribe_func=slow_transcribe)) as client:
        r1 = client.post("/jobs", data={"url": URL1})
        job1 = int(r1.headers["HX-Redirect"].split("/")[-1])
        assert first_entered.wait(5), "first job never reached the worker"
        assert store.get_job(job1).status == JOB_RUNNING

        # Second POST while the first is running: it must wait, never RUNNING.
        r2 = client.post("/jobs", data={"url": URL2})
        job2 = int(r2.headers["HX-Redirect"].split("/")[-1])
        assert store.get_job(job2).status in (JOB_PENDING, JOB_QUEUED), \
            f"second job must wait; got {store.get_job(job2).status}"
        time.sleep(1.0)  # give the worker a chance to (wrongly) claim job2
        assert store.get_job(job2).status in (JOB_PENDING, JOB_QUEUED), \
            "second job started while the first was still running"
        assert store.get_job(job1).status == JOB_RUNNING

        release.set()
        wait_for(store, job1, JOB_COMPLETE)
        wait_for(store, job2, JOB_COMPLETE)

    assert store.get_job(job1).status == JOB_COMPLETE
    assert store.get_job(job2).status == JOB_COMPLETE
    assert calls == [job1, job2], "jobs must be processed strictly in order"


# --------------------------------------------------------------------------- #
# global episode search
# --------------------------------------------------------------------------- #
def test_global_search_finds_episodes(store, tmp_path):
    store.upsert_episode(Episode(url=URL1, title=EP1, show_name="Test Show",
                                 state=VERIFIED, confidence=0.9))
    store.upsert_episode(Episode(url=URL2, title="Unrelated Title",
                                 show_name="Other Show"))
    with TestClient(make_app(store, tmp_path)) as client:
        r = client.get("/search", params={"q": "test episode"})
        assert r.status_code == 200
        assert EP1 in r.text
        assert "Unrelated Title" not in r.text
        assert "1 episode(s) matching" in r.text
        r2 = client.get("/search", params={"q": "nothing-here"})
        assert "No episodes match" in r2.text


# --------------------------------------------------------------------------- #
# PWA-lite assets
# --------------------------------------------------------------------------- #
def test_pwa_assets(store, tmp_path):
    with TestClient(make_app(store, tmp_path)) as client:
        assert client.get("/manifest.webmanifest").status_code == 200
        assert client.get("/sw.js").status_code == 200
        assert client.get("/static/htmx.min.js").status_code == 200
        assert client.get("/static/style.css").status_code == 200
        assert client.get("/static/icon-192.png").status_code == 200
        assert client.get("/static/icon-512.png").status_code == 200
        manifest = client.get("/manifest.webmanifest").json()
        assert manifest["display"] == "standalone"
        assert manifest["start_url"] == "/"
