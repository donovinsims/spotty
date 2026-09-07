"""Phase 2 web UI tests (FastAPI TestClient).

Everything is fully offline: resolve/download/transcribe are injected fakes,
so no network requests and no MLX model runs.  The in-process worker runs in a
background thread against a tmp-path SQLite database.
"""

from __future__ import annotations

import re
import sqlite3
import threading
import time
import wave
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from podcast_transcriber.config import Config
from podcast_transcriber.download import DownloadError
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
from podcast_transcriber.transcribe import TranscribeError, transcribe_job
from podcast_transcriber.verify import (
    REVIEW_REQUIRED,
    UNAVAILABLE,
    VERIFIED,
    Candidate,
    VerificationResult,
)
from podcast_transcriber.web import create_app
from podcast_transcriber.web.worker import Worker

URL1 = "https://open.spotify.com/episode/aaaaaaaaaa"
URL2 = "https://open.spotify.com/episode/bbbbbbbbbb"
EP1 = "My Test Episode"
EP2 = "Another Test Episode"

SW_PATH = Path(__file__).resolve().parents[1] / "src" / "podcast_transcriber" / "web" / "static" / "sw.js"


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
    # native-fallback form action stays on /jobs (no ?url= GET reload),
    # and swapped-in fragments get processed immediately (no settle-race).
    assert 'method="post" action="/jobs"' in r.text
    assert 'name="htmx-config"' in r.text
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
    ids = [int(m) for m in re.findall(r"/jobs/(\d+)\"", r.text)]
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
    assert "Verified" in r.text
    assert "97%" in r.text
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
        assert "Complete" in detail.text
        assert "View transcript" in detail.text
        assert f'hx-get="/jobs/{job_id}/status"' not in detail.text

        # transcript page
        tx = client.get(f"/jobs/{job_id}/transcript")
        assert tx.status_code == 200
        assert "Hello world this is a test podcast." in tx.text
        assert "00:00" in tx.text

        # download .txt (default) keeps old plain-text shape
        dl = client.get(f"/jobs/{job_id}/transcript/download")
        assert dl.status_code == 200
        assert dl.headers["content-type"].startswith("text/plain")
        assert "Test Show - My Test Episode.txt" in dl.headers["content-disposition"]
        assert "[00:00:00] Hello world this is a test podcast." in dl.text
        assert "Title: My Test Episode" in dl.text

        # download .md / .json carry smart filenames too
        md = client.get(f"/jobs/{job_id}/transcript/download", params={"format": "md"})
        assert md.status_code == 200
        assert 'show: "Test Show"' in md.text
        assert "Test Show - My Test Episode.md" in md.headers["content-disposition"]
        js = client.get(f"/jobs/{job_id}/transcript/download", params={"format": "json"})
        assert js.status_code == 200
        assert "My Test Episode" in js.text
        assert "Test Show - My Test Episode.json" in js.headers["content-disposition"]
        bad = client.get(f"/jobs/{job_id}/transcript/download", params={"format": "docx"})
        assert bad.status_code == 200 and "Title: My Test Episode" in bad.text  # falls back to txt

        # download .srt keeps subtitle body, gets a smart filename
        srt = client.get(f"/jobs/{job_id}/transcript/srt")
        assert srt.status_code == 200
        assert "-->" in srt.text
        assert "00:00:04,000" in srt.text
        assert "Test Show - My Test Episode.srt" in srt.headers["content-disposition"]

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
    # native (non-htmx) POST renders the FULL page, never a bare fragment
    assert "Search stored episodes" in r.text
    assert "<html" in r.text
    assert store.list_jobs() == []


# --------------------------------------------------------------------------- #
# status fragment
# --------------------------------------------------------------------------- #
def test_status_fragment_shows_progress(store, tmp_path):
    """A RUNNING job renders progress + keeps polling.  The worker claims the
    job and holds it (blocking transcribe) so the fragment is deterministic
    (the lifespan crash-recovery sweep would otherwise reset a pre-seeded
    RUNNING job to PENDING)."""
    release = threading.Event()

    def holding_transcribe(store_, job_id, *, model=None, chunk_minutes=None,
                           progress=None):
        for other in store_.active_jobs():
            if other.id != job_id:
                raise TranscribeError(f"job {other.id} is already active")
        assert store_.claim_job(job_id), "worker must win the claim"
        store_.update_job(job_id, chunk_count=4)
        release.wait(10)
        store_.update_job(job_id, status=JOB_COMPLETE)
        return {"job_id": job_id}

    eid = store.upsert_episode(Episode(url=URL1, title=EP1))
    job = store.create_job(eid)
    with TestClient(make_app(store, tmp_path,
                             transcribe_func=holding_transcribe)) as client:
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            if store.get_job(job.id).status == JOB_RUNNING:
                break
            time.sleep(0.02)
        assert store.get_job(job.id).status == JOB_RUNNING
        store.set_checkpoint(job.id, 0, "done")
        store.set_checkpoint(job.id, 1, "done")
        r = client.get(f"/jobs/{job.id}/status")
        release.set()
    assert r.status_code == 200
    assert "Transcribing" in r.text
    assert "50% done (2 of 4 parts)" in r.text
    assert 'style="width: 50%"' in r.text
    assert 'hx-trigger="every 5s' in r.text  # keeps polling


def test_status_fragment_terminal_stops_polling(store, tmp_path):
    eid = store.upsert_episode(Episode(url=URL1, title=EP1))
    job = store.create_job(eid)
    store.update_job(job.id, status=JOB_FAILED, error="boom")
    with TestClient(make_app(store, tmp_path)) as client:
        r = client.get(f"/jobs/{job.id}/status")
    assert r.status_code == 200
    assert "Failed" in r.text
    assert "boom" in r.text
    assert 'hx-trigger="every 5s' not in r.text  # polling stopped


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
        assert "1 episode matching" in r.text
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


# --------------------------------------------------------------------------- #
# F1: service worker caches ONLY the shell (never dynamic pages/fragments)
# --------------------------------------------------------------------------- #
def test_sw_js_intercepts_shell_only():
    sw = SW_PATH.read_text()
    # cache version bumped so previously-installed workers refresh
    assert "pt-shell-v3" in sw
    # the decision function exists and returns null for non-shell paths
    assert "function ptCacheStrategy" in sw
    assert "return null;" in sw
    # the fetch handler routes non-shell requests to the network default
    assert "strategy === null" in sw
    # shell assets still listed
    assert "/static/" in sw
    assert "manifest.webmanifest" in sw
    # L2: the network-first branch only caches OK responses (a 302 -> /login
    # page must never become the offline shell when auth is on)
    assert "response.ok" in sw


def test_sw_network_first_caches_only_ok_responses():
    """L2: mirror the sw.js network-first branch -- only res.ok responses are
    written to the cache; 3xx (auth redirect) and error responses are not."""
    sw = SW_PATH.read_text()
    assert "network-first" in sw
    assert "response.ok" in sw
    # the status check guards the cache.put
    ok_idx = sw.index("response.ok")
    put_idx = sw.index("cache.put(request, copy)")
    assert ok_idx < put_idx, "cache.put must be guarded by response.ok"


def test_sw_caches_shell_but_not_dynamic_status(store, tmp_path):
    """Simulate the service worker's cache semantics against the live app:
    the shell (/) is cached; the dynamic /jobs/<id>/status fragment is never
    cached, so polled state always comes back fresh."""
    sw = SW_PATH.read_text()
    m = re.search(r"const SHELL = \[(.*?)\];", sw, re.S)
    assert m, "SHELL array not found in sw.js"
    shell_paths = {p.strip().strip('"') for p in m.group(1).split(",") if p.strip()}

    def strategy(pathname: str):
        # Mirror sw.js ptCacheStrategy
        if pathname == "/":
            return "network-first"
        if pathname in shell_paths or pathname.startswith("/static/"):
            return "cache-first"
        return None

    cache: dict = {}
    release = threading.Event()

    def holding_transcribe(store_, job_id, *, model=None, chunk_minutes=None,
                           progress=None):
        for other in store_.active_jobs():
            if other.id != job_id:
                raise TranscribeError(f"job {other.id} is already active")
        assert store_.claim_job(job_id)
        release.wait(10)
        store_.update_job(job_id, status=JOB_COMPLETE)
        return {"job_id": job_id}

    eid = store.upsert_episode(Episode(url=URL1, title=EP1))
    with TestClient(make_app(store, tmp_path,
                             transcribe_func=holding_transcribe)) as client:
        # Shell is cached by the SW.
        for path in ("/", "/static/style.css", "/manifest.webmanifest"):
            r = client.get(path)
            assert r.status_code == 200
            assert strategy(path) is not None, path
            cache[path] = r.text
        assert "/" in cache

        job = store.create_job(eid)
        # The worker claims it (RUNNING) and holds it.
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            if store.get_job(job.id).status == JOB_RUNNING:
                break
            time.sleep(0.02)
        assert store.get_job(job.id).status == JOB_RUNNING

        status_url = f"/jobs/{job.id}/status"
        assert strategy(status_url) is None  # excluded by the SW
        r = client.get(status_url)
        assert "Transcribing" in r.text
        assert status_url not in cache  # never cached

        # State changes between polls -> next poll returns the NEW content.
        release.set()
        wait_for(store, job.id, JOB_COMPLETE)
        r2 = client.get(status_url)
        assert "Complete" in r2.text
        assert "Transcribing" not in r2.text
        assert status_url not in cache


# --------------------------------------------------------------------------- #
# F2: crash recovery (stale RUNNING sweep) + worker stop semantics
# --------------------------------------------------------------------------- #
def test_lifespan_recovers_stale_running_job(store, tmp_path):
    """A RUNNING job left by a killed process is swept to PENDING on startup
    and drains to COMPLETE (single-active slot unblocked)."""
    eid = store.upsert_episode(Episode(url=URL1, title=EP1))
    job = store.create_job(eid)
    store.update_job(job.id, status=JOB_RUNNING, error="stale error from crash")
    with TestClient(make_app(store, tmp_path)) as client:
        wait_for(store, job.id, JOB_COMPLETE)
    assert store.get_job(job.id).status == JOB_COMPLETE
    assert store.get_job(job.id).error is None  # sweep cleared the stale error


def test_lifespan_recovers_stale_running_and_drains_queued(store, tmp_path):
    """Stale RUNNING + a waiting PENDING + a QUEUED job all drain after the
    recovery sweep (the stale job re-queues behind the waiting PENDING one)."""
    eid1 = store.upsert_episode(Episode(url=URL1, title=EP1))
    job1 = store.create_job(eid1)
    store.update_job(job1.id, status=JOB_RUNNING)
    # With the slot RUNNING, a second job can still become PENDING (the index
    # allows one PENDING + one RUNNING)...
    eid2 = store.upsert_episode(Episode(url=URL2, title=EP2))
    job2 = store.create_job(eid2)
    assert store.get_job(job2.id).status == JOB_PENDING
    # ...and a third queues as QUEUED while a PENDING job holds the slot.
    eid3 = store.upsert_episode(Episode(url=URL2 + "3", title=EP2))
    job3 = store.create_job_queued(eid3)
    assert store.get_job(job3.id).status == JOB_QUEUED

    with TestClient(make_app(store, tmp_path)) as client:
        wait_for(store, job1.id, JOB_COMPLETE)
        wait_for(store, job2.id, JOB_COMPLETE)
        wait_for(store, job3.id, JOB_COMPLETE)
    assert store.get_job(job1.id).status == JOB_COMPLETE
    assert store.get_job(job2.id).status == JOB_COMPLETE
    assert store.get_job(job3.id).status == JOB_COMPLETE


def test_worker_stop_marks_inflight_job_failed(store, tmp_path):
    """Worker.stop() with an in-flight job that cannot finish in time marks it
    FAILED ("server shutdown") instead of abandoning it RUNNING."""
    release = threading.Event()

    def stuck_transcribe(store_, job_id, *, model=None, chunk_minutes=None,
                         progress=None):
        store_.claim_job(job_id)
        release.wait(30)  # never finishes on its own

    eid = store.upsert_episode(Episode(url=URL1, title=EP1))
    job = store.create_job(eid)
    cfg = Config(data_dir=str(tmp_path / "data"))
    w = Worker(store.db_path, cfg, download_func=fake_download,
               transcribe_func=stuck_transcribe)
    w.start()
    try:
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            if store.get_job(job.id).status == JOB_RUNNING:
                break
            time.sleep(0.02)
        assert store.get_job(job.id).status == JOB_RUNNING
        w.stop(timeout=0.3)
        job = store.get_job(job.id)
        assert job.status == JOB_FAILED
        assert "server shutdown" in job.error
    finally:
        release.set()
        w.stop()


# --------------------------------------------------------------------------- #
# F3: slot-busy race must never mark a job FAILED
# --------------------------------------------------------------------------- #
def test_worker_slot_race_leaves_job_pending(store, tmp_path):
    """Job B stays PENDING (never FAILED) when another process holds the
    single active slot; it drains once the slot frees.  The Worker is driven
    directly (not via the app) so the lifespan recovery sweep cannot reset the
    deliberately-RUNNING job A."""
    eid_a = store.upsert_episode(Episode(url=URL1, title=EP1))
    job_a = store.create_job(eid_a)
    eid_b = store.upsert_episode(Episode(url=URL2, title=EP2))
    job_b = store.create_job_queued(eid_b)  # PENDING slot -> QUEUED

    # A second Store connection = a concurrent process (e.g. Phase 1 CLI).
    s2 = Store(store.db_path)
    try:
        s2.update_job(job_a.id, status=JOB_RUNNING)

        def race_transcribe(store_, job_id, *, model=None, chunk_minutes=None,
                            progress=None):
            # Mirror the transcribe_job claim race: claim directly (no guard
            # pre-check), so the partial-unique-index IntegrityError fires.
            if not store_.claim_job(job_id):
                raise TranscribeError(f"job {job_id} not pending")
            store_.update_job(job_id, status=JOB_COMPLETE)
            return {"job_id": job_id}

        cfg = Config(data_dir=str(tmp_path / "data"))
        w = Worker(store.db_path, cfg, download_func=fake_download,
                   transcribe_func=race_transcribe)
        w.start()
        try:
            time.sleep(1.5)  # let the worker try (and fail) to claim job B
            b = store.get_job(job_b.id)
            assert b.status == JOB_PENDING, \
                f"job B must stay PENDING; got {b.status}"
            assert b.error is None, b.error
            # Free the slot -> job B now drains.
            s2.update_job(job_a.id, status=JOB_COMPLETE)
            deadline = time.monotonic() + 8
            while time.monotonic() < deadline:
                if store.get_job(job_b.id).status == JOB_COMPLETE:
                    break
                time.sleep(0.05)
            assert store.get_job(job_b.id).status == JOB_COMPLETE
        finally:
            w.stop()
    finally:
        s2.close()


def test_transcribe_job_converts_slot_race_integrity_error(store, tmp_path,
                                                           monkeypatch):
    """transcribe_job's claim path converts the partial-unique-index
    IntegrityError into TranscribeError, leaving the job PENDING."""
    wav = make_wav(tmp_path / "clip.wav")
    eid = store.upsert_episode(Episode(url=URL1, title=EP1, audio_url=str(wav)))
    job = store.create_job(eid)

    monkeypatch.setattr(store, "active_jobs", lambda: [])

    def boom_claim(job_id):
        raise sqlite3.IntegrityError("UNIQUE constraint failed: jobs.status")

    monkeypatch.setattr(store, "claim_job", boom_claim)

    with pytest.raises(TranscribeError, match="slot is busy"):
        transcribe_job(store, job.id, chunk_minutes=1)
    assert store.get_job(job.id).status == JOB_PENDING
    assert store.get_job(job.id).error is None


# --------------------------------------------------------------------------- #
# F5: worker failure paths
# --------------------------------------------------------------------------- #
def test_worker_marks_failed_when_transcribe_raises(store, tmp_path):
    """A transcribe failure after the claim marks the job FAILED with the
    error, and the status fragment renders it."""
    def boom_transcribe(store_, job_id, *, model=None, chunk_minutes=None,
                        progress=None):
        store_.claim_job(job_id)
        raise RuntimeError("boom in transcribe")

    eid = store.upsert_episode(Episode(url=URL1, title=EP1))
    job = store.create_job(eid)
    with TestClient(make_app(store, tmp_path,
                             transcribe_func=boom_transcribe)) as client:
        wait_for(store, job.id, JOB_FAILED)
        job = store.get_job(job.id)
        assert "boom in transcribe" in job.error
        r = client.get(f"/jobs/{job.id}/status")
        assert "Failed" in r.text
        assert "boom in transcribe" in r.text


def test_worker_marks_failed_on_download_error(store, tmp_path):
    def bad_download(store_, episode_id, audio_dir, *, progress=None, **kwargs):
        raise DownloadError("bad audio source")

    eid = store.upsert_episode(Episode(
        url=URL1, title=EP1, audio_url="https://cdn.example.test/bad.mp3"))
    job = store.create_job(eid)
    with TestClient(make_app(store, tmp_path,
                             download_func=bad_download)) as client:
        wait_for(store, job.id, JOB_FAILED)
        job = store.get_job(job.id)
        assert job.error == "bad audio source"


# --------------------------------------------------------------------------- #
# F6: raw exception text must not reach the UI
# --------------------------------------------------------------------------- #
def test_resolve_failure_hides_internal_detail(store, tmp_path):
    def explode_resolve(url, **kwargs):
        raise RuntimeError("https://internal.corp/secret exploded")

    with TestClient(make_app(store, tmp_path,
                             resolve_func=explode_resolve)) as client:
        r = client.post("/jobs", data={"url": URL1})
    assert r.status_code == 200
    assert "Resolution failed" in r.text
    assert "internal.corp" not in r.text
    assert "exploded" not in r.text


# --------------------------------------------------------------------------- #
# F9: search highlight must survive HTML entities
# --------------------------------------------------------------------------- #
def test_search_highlight_survives_entities(store, tmp_path):
    eid = store.upsert_episode(Episode(url=URL1, title=EP1))
    job = store.create_job(eid)
    store.update_job(job.id, status=JOB_COMPLETE)
    tx = store.upsert_transcript(job.id, eid, "en")
    store.add_segment(job.id, tx, 0, 0.0, 2.0, "Our R&D team ships weekly.")
    with TestClient(make_app(store, tmp_path)) as client:
        r = client.post(f"/jobs/{job.id}/transcript/search", data={"q": "&"})
    assert r.status_code == 200
    assert "<mark>&amp;</mark>" in r.text
    assert "R<mark>&amp;</mark>D" in r.text


# --------------------------------------------------------------------------- #
# F10: 422 / 500 handlers (HTMX-aware)
# --------------------------------------------------------------------------- #
def test_422_renders_error_page(store, tmp_path):
    with TestClient(make_app(store, tmp_path)) as client:
        r = client.post("/jobs", data={})  # missing url form field
    assert r.status_code == 422
    assert "422" in r.text
    assert "Invalid request parameters" in r.text


def test_422_htmx_returns_fragment(store, tmp_path):
    with TestClient(make_app(store, tmp_path)) as client:
        r = client.post("/jobs", data={}, headers={"HX-Request": "true"})
    assert r.status_code == 422
    assert "Invalid request parameters" in r.text
    assert "<html" not in r.text  # fragment, not the full page


def test_500_renders_error_page_and_hides_detail(store, tmp_path):
    app = make_app(store, tmp_path)

    @app.get("/boom")
    def boom():
        raise RuntimeError("kaboom internal detail")

    # ServerErrorMiddleware always re-raises for test clients unless told not
    # to; the response (rendered by our handler) is what we assert on.
    with TestClient(app, raise_server_exceptions=False) as client:
        r = client.get("/boom")
    assert r.status_code == 500
    assert "Internal server error" in r.text
    assert "kaboom" not in r.text


# --------------------------------------------------------------------------- #
# F11: tracking params must not duplicate episodes
# --------------------------------------------------------------------------- #
def test_episode_url_deduped_across_tracking_params(store, tmp_path):
    wav = make_wav(tmp_path / "clip.wav")
    ver_resolution = resolution(URL1)
    ver_resolution.result.audio_url = str(wav)

    def local_resolve(url, **kwargs):
        ver_resolution.source_url = url  # echo the pasted URL (with params)
        return ver_resolution

    with TestClient(make_app(store, tmp_path,
                             resolve_func=local_resolve)) as client:
        client.post("/jobs", data={"url": URL1 + "?si=abc123&utm_source=share"})
        client.post("/jobs", data={"url": URL1})
    eps = store.find_episodes(EP1)
    assert len(eps) == 1
    assert eps[0].url == URL1
