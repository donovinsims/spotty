"""Download command tests -- fully offline via httpx.MockTransport."""

from __future__ import annotations

from pathlib import Path

import httpx
import pytest

from podcast_transcriber import download
from podcast_transcriber.download import DownloadError, download_episode
from podcast_transcriber.store import JOB_PENDING, Episode

FIXTURE = Path(__file__).resolve().parents[1] / "data" / "fixture_8s.wav"


@pytest.fixture(scope="module")
def wav_bytes() -> bytes:
    return FIXTURE.read_bytes()


def test_download_remote_lands_in_audio_dir_and_creates_job(store, tmp_path, wav_bytes):
    audio_dir = tmp_path / "audio"

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.host == "cdn.example.test"
        return httpx.Response(
            200, content=wav_bytes, headers={"Content-Type": "audio/wav"}
        )

    client = httpx.Client(transport=httpx.MockTransport(handler), follow_redirects=True)
    ep = Episode(
        url="https://open.spotify.com/episode/xyz",
        title="Ep",
        state="VERIFIED",
        confidence=1.0,
        audio_url="https://cdn.example.test/ep/8s.wav",
    )
    eid = store.upsert_episode(ep)

    out = download_episode(store, eid, audio_dir, client=client)

    dest = audio_dir / f"{eid}.wav"
    assert dest.is_file(), out
    assert dest.stat().st_size == len(wav_bytes)
    # audio_url updated to the local path
    assert store.get_episode(eid).audio_url == str(dest)
    # a PENDING job was created
    jobs = [j for j in store.list_jobs() if j.episode_id == eid]
    assert len(jobs) == 1
    assert jobs[0].status == JOB_PENDING
    # download idempotent: second call reuses existing job
    out2 = download_episode(store, eid, audio_dir, client=client)
    assert out2["job"].id == jobs[0].id
    assert len([j for j in store.list_jobs() if j.episode_id == eid]) == 1


def test_download_rejects_non_http_scheme(store, tmp_path):
    ep = Episode(url="https://open.spotify.com/episode/a2", title="Ep",
                 audio_url="ftp://cdn.example.test/ep.mp3")
    eid = store.upsert_episode(ep)
    with pytest.raises(DownloadError, match="scheme"):
        download_episode(store, eid, tmp_path)


def test_download_already_local_skips_network(store, tmp_path, wav_bytes):
    local = tmp_path / "already.wav"
    local.write_bytes(wav_bytes)
    ep = Episode(url="https://open.spotify.com/episode/l", title="Local",
                 audio_url=str(local))
    eid = store.upsert_episode(ep)
    out = download_episode(store, eid, tmp_path / "audio")
    assert out["audio_path"] == str(local)
    assert store.get_episode(eid).audio_url == str(local)
    jobs = [j for j in store.list_jobs() if j.episode_id == eid]
    assert len(jobs) == 1 and jobs[0].status == JOB_PENDING


def test_download_missing_episode_raises(store, tmp_path):
    with pytest.raises(DownloadError, match="not found"):
        download_episode(store, 999, tmp_path)


def test_download_http_error_raises(store, tmp_path):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(404)

    client = httpx.Client(transport=httpx.MockTransport(handler))
    ep = Episode(url="https://open.spotify.com/episode/err", audio_url="https://cdn/x.mp3")
    eid = store.upsert_episode(ep)
    with pytest.raises(DownloadError, match="HTTP 404"):
        download_episode(store, eid, tmp_path / "audio", client=client)
    # broken download must not update audio_url
    assert store.get_episode(eid).audio_url == "https://cdn/x.mp3"