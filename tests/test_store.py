"""SQLite store tests: schema, migrations, single-active-job, checkpoints."""

from __future__ import annotations

import sqlite3

import pytest

from podcast_transcriber.store import (
    JOB_COMPLETE,
    JOB_FAILED,
    JOB_PENDING,
    JOB_RUNNING,
    VERIFIED,
    Episode,
    Store,
)


def test_schema_version_and_tables(store: Store):
    tables = {
        r["name"]
        for r in store._conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        )
    }
    assert {"episodes", "jobs", "transcripts", "segments", "checkpoints", "schema_version"} <= tables
    row = store._conn.execute("SELECT version FROM schema_version").fetchone()
    assert row["version"] == 1


def test_wal_and_foreign_keys(store: Store):
    mode = store._conn.execute("PRAGMA journal_mode").fetchone()[0]
    assert mode == "wal"
    assert store._conn.execute("PRAGMA foreign_keys").fetchone()[0] == 1


def test_upsert_episode_and_find(store: Store):
    ep = Episode(url="https://open.spotify.com/episode/zzz", title="Hello",
                 state=VERIFIED, confidence=0.9, audio_url="https://cdn/x.mp3")
    eid = store.upsert_episode(ep)
    got = store.get_episode(eid)
    assert got.title == "Hello"
    assert got.state == VERIFIED
    # upsert same url updates, does not duplicate
    ep2 = Episode(url="https://open.spotify.com/episode/zzz", title="Hello 2",
                  state="REVIEW_REQUIRED", confidence=0.4)
    eid2 = store.upsert_episode(ep2)
    assert eid2 == eid
    assert store.get_episode(eid).title == "Hello 2"
    hits = store.find_episodes("hello")
    assert [h.id for h in hits] == [eid]


def test_single_active_job_db_enforced(store: Store):
    eid = store.upsert_episode(Episode(url="https://x/ep/1"))
    j1 = store.create_job(eid)  # PENDING counts as the one active slot
    assert j1.status == JOB_PENDING
    assert store.has_active_job()
    # A second job cannot be created while one is already queued/running.
    with pytest.raises(sqlite3.IntegrityError):
        store.create_job(eid)
    # Running the first keeps the slot locked; forcing a second RUNNING fails.
    store.update_job(j1.id, status=JOB_RUNNING)
    store.update_job(j1.id, status=JOB_FAILED, error="boom")
    assert not store.has_active_job()
    # Slot is free again once the earlier job is terminal.
    j2 = store.create_job(eid)
    assert store.has_active_job()
    assert j2.status == JOB_PENDING


def test_job_lifecycle_and_complete(store: Store):
    eid = store.upsert_episode(Episode(url="https://x/ep/2"))
    j = store.create_job(eid, model="mlx-community/whisper-tiny", chunk_minutes=10.0)
    store.update_job(j.id, status=JOB_RUNNING)
    store.update_job(j.id, status=JOB_COMPLETE, chunk_count=3)
    got = store.get_job(j.id)
    assert got.status == JOB_COMPLETE
    assert got.chunk_count == 3
    store.update_job(j.id, status=JOB_FAILED, error="boom")
    assert store.get_job(j.id).error == "boom"


def test_checkpoints_and_resume_skip(store: Store):
    eid = store.upsert_episode(Episode(url="https://x/ep/3"))
    j = store.create_job(eid)
    assert store.get_checkpoint(j.id, 0) is None
    store.set_checkpoint(j.id, 0, "done", audio_path="/tmp/a.wav",
                         result={"text": "seeded", "segments": 1})
    cp = store.get_checkpoint(j.id, 0)
    assert cp["status"] == "done"
    assert cp["result"]["text"] == "seeded"
    # overwrite works (idempotent resume)
    store.set_checkpoint(j.id, 0, "done", audio_path="/tmp/a.wav",
                         result={"text": "seeded2", "segments": 1})
    assert store.get_checkpoint(j.id, 0)["result"]["text"] == "seeded2"
    assert len(store.checkpoints_for_job(j.id)) == 1


def test_transcript_segments(store: Store):
    eid = store.upsert_episode(Episode(url="https://x/ep/4"))
    j = store.create_job(eid)
    tx = store.upsert_transcript(j.id, eid, "en")
    store.add_segment(j.id, tx, 0, 0.0, 5.0, "hello")
    store.add_segment(j.id, tx, 0, 5.0, 9.0, "world")
    segs = store.segments_for_job(j.id)
    assert [s["text"] for s in segs] == ["hello", "world"]
    t = store.get_transcript(j.id)
    assert t.language == "en"
    assert t.segments == 2