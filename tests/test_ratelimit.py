"""Phase 4 tests: per-IP rate limiting + queue cap on POST /jobs.

Offline: resolve/download/transcribe are injected fakes; the limiter and the
queue-cap logic are exercised through the FastAPI TestClient (and directly on
SlidingWindowLimiter for the window semantics).
"""

from __future__ import annotations

from fastapi.testclient import TestClient
import pytest

from podcast_transcriber.config import Config
from podcast_transcriber.resolve import Resolution, SpotifyMeta
from podcast_transcriber.store import (
    JOB_COMPLETE,
    JOB_FAILED,
    JOB_PENDING,
    Episode,
    Store,
)
from podcast_transcriber.verify import VERIFIED, Candidate, VerificationResult
from podcast_transcriber.web import create_app
from podcast_transcriber.web.ratelimit import SlidingWindowLimiter

URL1 = "https://open.spotify.com/episode/rllimit1"
URL2 = "https://open.spotify.com/episode/rllimit2"


def fake_resolve(url, **kwargs):
    if "spotify.com/episode" not in url:
        raise ValueError(f"Not a Spotify episode URL: {url!r}")
    meta = SpotifyMeta(spotify_id="rl", url=url, episode_title="RL Ep",
                       show_name="S", duration_seconds=60.0)
    result = VerificationResult(
        state=VERIFIED, confidence=0.99, reason="ok",
        audio_url="https://cdn.example.test/ep.mp3", matched_title="RL Ep",
        candidates=[Candidate(audio_url="https://cdn.example.test/ep.mp3",
                              title="RL Ep", confidence=0.99)],
    )
    return Resolution(spotify_id="rl", source_url=url, metadata=meta,
                      feed_url="https://feed.example.test/rss", result=result)


def fake_download(*a, **kw):
    return {"episode_id": a[1], "audio_path": "/x"}


def fake_transcribe(store_, job_id, *, model=None, chunk_minutes=None, progress=None):
    store_.claim_job(job_id)
    store_.update_job(job_id, status=JOB_COMPLETE)
    return {"job_id": job_id}


def make_app(store: Store, tmp_path, **overrides):
    cfg = Config(data_dir=str(tmp_path / "data"))
    kwargs = dict(
        resolve_func=fake_resolve,
        download_func=fake_download,
        transcribe_func=fake_transcribe,
    )
    kwargs.update(overrides)
    return create_app(store=store, cfg=cfg, **kwargs)


# --------------------------------------------------------------------------- #
# SlidingWindowLimiter unit semantics
# --------------------------------------------------------------------------- #
def test_limiter_allows_up_to_limit_then_blocks():
    lim = SlidingWindowLimiter(limit_per_min=3, window_seconds=60)
    for _ in range(3):
        allowed, retry = lim.allow("1.2.3.4")
        assert allowed is True
        assert retry == 0
    allowed, retry = lim.allow("1.2.3.4")
    assert allowed is False
    assert retry >= 1


def test_limiter_is_per_key():
    lim = SlidingWindowLimiter(limit_per_min=1, window_seconds=60)
    assert lim.allow("a")[0] is True
    assert lim.allow("b")[0] is True  # different key, unaffected
    assert lim.allow("a")[0] is False
    assert lim.allow("b")[0] is False


def test_limiter_window_slides(monkeypatch):
    """Hits older than the window stop counting -> allowance returns."""
    import time as time_mod

    lim = SlidingWindowLimiter(limit_per_min=1, window_seconds=60)
    fake_now = [1000.0]
    monkeypatch.setattr(time_mod, "monotonic", lambda: fake_now[0])
    assert lim.allow("k")[0] is True
    assert lim.allow("k")[0] is False
    fake_now[0] = 1000.0 + 61.0  # window elapses
    assert lim.allow("k")[0] is True


def test_limiter_min_limit_is_one():
    lim = SlidingWindowLimiter(limit_per_min=0)
    assert lim.limit == 1


# --------------------------------------------------------------------------- #
# rate limit on POST /jobs
# --------------------------------------------------------------------------- #
def test_rate_limit_429_with_retry_after(store, tmp_path):
    cfg = Config(data_dir=str(tmp_path / "data"), rate_limit=2)
    app = create_app(store=store, cfg=cfg, resolve_func=fake_resolve,
                     download_func=fake_download, transcribe_func=fake_transcribe)
    with TestClient(app) as client:
        # Two allowed, third blocked -- bad URL keeps it offline but still
        # consumes the allowance (limit is on submissions, not outcomes).
        for url in (URL1, URL2):
            r = client.post("/jobs", data={"url": url})
            assert r.status_code == 200, r.text
        r3 = client.post("/jobs", data={"url": "https://x.invalid/nope"})
        assert r3.status_code == 429
        assert "Retry-After" in r3.headers
        assert int(r3.headers["Retry-After"]) >= 1
    # rate limit is per-app; a fresh app starts clean
    with TestClient(create_app(store=store, cfg=cfg, resolve_func=fake_resolve,
                               download_func=fake_download,
                               transcribe_func=fake_transcribe)) as client:
        r = client.post("/jobs", data={"url": URL1})
        assert r.status_code == 200


def test_rate_limit_htmx_gets_fragment(store, tmp_path):
    cfg = Config(data_dir=str(tmp_path / "data"), rate_limit=1)
    app = create_app(store=store, cfg=cfg, resolve_func=fake_resolve,
                     download_func=fake_download, transcribe_func=fake_transcribe)
    with TestClient(app) as client:
        client.post("/jobs", data={"url": URL1})
        r = client.post("/jobs", data={"url": URL1}, headers={"HX-Request": "true"})
        assert r.status_code == 200  # H7: preserves URL in form fragment
        assert "<html" not in r.text  # fragment, not a full page
        assert "Too many jobs" in r.text


def test_rate_limit_api_gets_json(store, tmp_path):
    cfg = Config(data_dir=str(tmp_path / "data"), rate_limit=1)
    app = create_app(store=store, cfg=cfg, resolve_func=fake_resolve,
                     download_func=fake_download, transcribe_func=fake_transcribe)
    with TestClient(app) as client:
        client.post("/jobs", data={"url": URL1})
        r = client.post("/jobs", data={"url": URL1}, headers={"accept": "application/json"})
        assert r.status_code == 429
        assert r.json()["detail"]
        assert "Retry-After" in r.headers


def test_rate_limit_xff_only_trusted_when_configured(store, tmp_path):
    """With PT_TRUST_PROXY off, a spoofed X-Forwarded-For is ignored (all
    requests share one bucket); with it on, distinct XFF values get separate
    buckets."""
    cfg = Config(data_dir=str(tmp_path / "data"), rate_limit=1, trust_proxy=False)
    app = create_app(store=store, cfg=cfg, resolve_func=fake_resolve,
                     download_func=fake_download, transcribe_func=fake_transcribe)
    with TestClient(app) as client:
        client.post("/jobs", data={"url": URL1})
        # Same client IP, fake XFF: still limited (header not trusted).
        r = client.post("/jobs", data={"url": URL2},
                        headers={"X-Forwarded-For": "9.9.9.9"})
        assert r.status_code == 429

    cfg2 = Config(data_dir=str(tmp_path / "data"), rate_limit=1, trust_proxy=True)
    app2 = create_app(store=store, cfg=cfg2, resolve_func=fake_resolve,
                      download_func=fake_download, transcribe_func=fake_transcribe)
    with TestClient(app2) as client:
        client.post("/jobs", data={"url": URL1})
        r = client.post("/jobs", data={"url": URL2},
                        headers={"X-Forwarded-For": "9.9.9.9"})
        assert r.status_code == 200  # trusted proxy -> distinct bucket


# --------------------------------------------------------------------------- #
# queue cap on POST /jobs
# --------------------------------------------------------------------------- #
def test_queue_cap_409_when_full(store, tmp_path, monkeypatch):
    """When PENDING+QUEUED >= PT_MAX_QUEUED, POST /jobs -> 409 with a clear
    message, before any resolve happens."""
    import podcast_transcriber.web.app as app_mod

    class FullStore:
        def count_queued_jobs(self):
            return 50

    monkeypatch.setattr(app_mod, "_store_for", lambda db_path: FullStore())
    cfg = Config(data_dir=str(tmp_path / "data"), max_queued=50)
    app = create_app(store=store, cfg=cfg, resolve_func=fake_resolve,
                     download_func=fake_download, transcribe_func=fake_transcribe)
    with TestClient(app) as client:
        r = client.post("/jobs", data={"url": URL1})
    assert r.status_code == 409
    assert "already queued" in r.text.lower()
    assert store.list_jobs() == []  # no job was created


def test_queue_cap_does_not_block_under_limit(store, tmp_path):
    cfg = Config(data_dir=str(tmp_path / "data"), max_queued=50)
    app = create_app(store=store, cfg=cfg, resolve_func=fake_resolve,
                     download_func=fake_download, transcribe_func=fake_transcribe)
    with TestClient(app) as client:
        r = client.post("/jobs", data={"url": URL1})
    assert r.status_code == 200
    assert store.list_jobs() != []


def test_queue_cap_counts_pending_jobs(store, tmp_path, monkeypatch):
    """A PENDING job already in the DB counts toward the cap."""
    from podcast_transcriber.web import worker as worker_mod

    class NoopWorker:
        running = False
        def start(self): pass
        def stop(self, timeout=None): pass

    monkeypatch.setattr(worker_mod, "get_worker",
                        lambda *a, **kw: NoopWorker())
    monkeypatch.setattr(worker_mod, "stop_worker",
                        lambda *a, **kw: None)

    eid = store.upsert_episode(Episode(url=URL1, title="Seeded"))
    job = store.create_job(eid)
    assert job.status == JOB_PENDING
    cfg = Config(data_dir=str(tmp_path / "data"), max_queued=1)
    app = create_app(store=store, cfg=cfg, resolve_func=fake_resolve,
                     download_func=fake_download, transcribe_func=fake_transcribe)
    with TestClient(app) as client:
        r = client.post("/jobs", data={"url": URL2})
    assert r.status_code == 409
    assert "1 job(s) already queued" in r.text
