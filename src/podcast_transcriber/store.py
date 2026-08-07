"""SQLite persistence layer (stdlib sqlite3 only).

- WAL journal mode, foreign keys enabled.
- schema_version table + migrations.
- Tables: episodes, jobs, transcripts, segments, checkpoints.

All writes are transactional.  The jobs table enforces "one active job at a
time" via a partial unique index on jobs(status) WHERE status='RUNNING' --
SQLite supports partial indexes, giving us a DB-level guarantee.
"""

from __future__ import annotations

import json
import logging
import sqlite3
from contextlib import closing
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Iterator, List, Optional

log = logging.getLogger(__name__)

SCHEMA_VERSION = 1

# Job statuses used across the app.
JOB_PENDING = "PENDING"
JOB_RUNNING = "RUNNING"
JOB_COMPLETE = "COMPLETE"
JOB_FAILED = "FAILED"
ACTIVE_STATUSES = (JOB_PENDING, JOB_RUNNING)

# Episode verification states.
VERIFIED = "VERIFIED"
REVIEW_REQUIRED = "REVIEW_REQUIRED"
UNAVAILABLE = "UNAVAILABLE"

_MIGRATIONS: Dict[int, str] = {
    0: """
    CREATE TABLE schema_version (
        version INTEGER NOT NULL
    );
    """,
    1: """
    CREATE TABLE IF NOT EXISTS episodes (
        id            INTEGER PRIMARY KEY AUTOINCREMENT,
        spotify_id    TEXT,
        url           TEXT UNIQUE NOT NULL,
        title         TEXT,
        show_name     TEXT,
        publisher     TEXT,
        rss_url       TEXT,
        audio_url     TEXT,
        duration_seconds REAL,
        state         TEXT NOT NULL DEFAULT 'UNAVAILABLE',
        confidence    REAL,
        reason        TEXT,
        candidates    TEXT,
        parsed_at     TEXT
    );

    CREATE TABLE IF NOT EXISTS jobs (
        id            INTEGER PRIMARY KEY AUTOINCREMENT,
        episode_id    INTEGER NOT NULL REFERENCES episodes(id) ON DELETE CASCADE,
        status        TEXT NOT NULL DEFAULT 'PENDING',
        model         TEXT,
        chunk_minutes REAL,
        chunk_count   INTEGER,
        error         TEXT,
        created_at    TEXT NOT NULL,
        updated_at    TEXT
    );
    -- One active (pending/running) job at a time, enforced at the DB level.
    CREATE UNIQUE INDEX IF NOT EXISTS ux_jobs_single_active
        ON jobs(status) WHERE status IN ('PENDING', 'RUNNING');

    CREATE TABLE IF NOT EXISTS transcripts (
        id         INTEGER PRIMARY KEY AUTOINCREMENT,
        job_id     INTEGER NOT NULL REFERENCES jobs(id) ON DELETE CASCADE,
        episode_id INTEGER NOT NULL REFERENCES episodes(id) ON DELETE CASCADE,
        language   TEXT,
        segments   INTEGER,
        created_at TEXT NOT NULL
    );
    CREATE UNIQUE INDEX IF NOT EXISTS idx_transcripts_job ON transcripts(job_id);

    CREATE TABLE IF NOT EXISTS segments (
        id            INTEGER PRIMARY KEY AUTOINCREMENT,
        transcript_id INTEGER NOT NULL REFERENCES transcripts(id) ON DELETE CASCADE,
        job_id        INTEGER NOT NULL REFERENCES jobs(id) ON DELETE CASCADE,
        chunk_index   INTEGER NOT NULL,
        start_time    REAL,
        end_time      REAL,
        text          TEXT
    );
    CREATE INDEX IF NOT EXISTS idx_segments_job ON segments(job_id, chunk_index);

    CREATE TABLE IF NOT EXISTS checkpoints (
        id          INTEGER PRIMARY KEY AUTOINCREMENT,
        job_id      INTEGER NOT NULL REFERENCES jobs(id) ON DELETE CASCADE,
        chunk_index INTEGER NOT NULL,
        status      TEXT NOT NULL,
        audio_path  TEXT,
        result      TEXT,
        updated_at  TEXT NOT NULL,
        UNIQUE (job_id, chunk_index)
    );
    """,
}


@dataclass
class Episode:
    id: Optional[int] = None
    spotify_id: Optional[str] = None
    url: str = ""
    title: Optional[str] = None
    show_name: Optional[str] = None
    publisher: Optional[str] = None
    rss_url: Optional[str] = None
    audio_url: Optional[str] = None
    duration_seconds: Optional[float] = None
    state: str = UNAVAILABLE
    confidence: Optional[float] = None
    reason: Optional[str] = None
    candidates: List[Dict[str, Any]] = field(default_factory=list)
    parsed_at: Optional[str] = None

    @classmethod
    def from_row(cls, row: sqlite3.Row) -> "Episode":
        return cls(
            id=row["id"],
            spotify_id=row["spotify_id"],
            url=row["url"],
            title=row["title"],
            show_name=row["show_name"],
            publisher=row["publisher"],
            rss_url=row["rss_url"],
            audio_url=row["audio_url"],
            duration_seconds=row["duration_seconds"],
            state=row["state"] or "UNAVAILABLE",
            confidence=row["confidence"],
            reason=row["reason"],
            candidates=json.loads(row["candidates"]) if row["candidates"] else [],
            parsed_at=row["parsed_at"],
        )


@dataclass
class Job:
    id: Optional[int] = None
    episode_id: Optional[int] = None
    status: str = JOB_PENDING
    model: Optional[str] = None
    chunk_minutes: Optional[float] = None
    chunk_count: Optional[int] = None
    error: Optional[str] = None
    created_at: Optional[str] = None
    updated_at: Optional[str] = None

    @classmethod
    def from_row(cls, row: sqlite3.Row) -> "Job":
        return cls(
            id=row["id"],
            episode_id=row["episode_id"],
            status=row["status"],
            model=row["model"],
            chunk_minutes=row["chunk_minutes"],
            chunk_count=row["chunk_count"],
            error=row["error"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )


@dataclass
class Transcript:
    id: Optional[int] = None
    job_id: Optional[int] = None
    episode_id: Optional[int] = None
    language: Optional[str] = None
    segments: int = 0
    created_at: Optional[str] = None

    @classmethod
    def from_row(cls, row: sqlite3.Row) -> "Transcript":
        return cls(
            id=row["id"],
            job_id=row["job_id"],
            episode_id=row["episode_id"],
            language=row["language"],
            segments=row["segments"],
            created_at=row["created_at"],
        )


def _now() -> str:
    import datetime

    return datetime.datetime.now(datetime.timezone.utc).isoformat()


class Store:
    def __init__(self, db_path: str | Path) -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(self.db_path))
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL;")
        self._conn.execute("PRAGMA foreign_keys=ON;")
        self._conn.execute("PRAGMA busy_timeout=5000;")
        self.migrate()

    # ------------------------------------------------------------------ #
    # helpers
    # ------------------------------------------------------------------ #
    def connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.db_path))
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL;")
        conn.execute("PRAGMA foreign_keys=ON;")
        conn.execute("PRAGMA busy_timeout=5000;")
        return conn

    def _write(self, fn) -> Any:
        """Open a fresh connection, run `fn(conn)` in a transaction, commit, close."""
        with closing(self.connect()) as conn:
            conn.execute("BEGIN")
            try:
                result = fn(conn)
                conn.commit()
                return result
            except Exception:
                conn.rollback()
                raise

    def _read(self, fn) -> Any:
        with closing(self.connect()) as conn:
            return fn(conn)

    def migrate(self) -> None:
        cur = self._conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='schema_version'"
        )
        if cur.fetchone() is None:
            self._conn.execute("CREATE TABLE schema_version (version INTEGER NOT NULL);")
            self._conn.execute("INSERT INTO schema_version (version) VALUES (0)")
            self._conn.commit()
        cur = self._conn.execute("SELECT version FROM schema_version LIMIT 1")
        current = cur.fetchone()["version"]
        for v in range(current + 1, SCHEMA_VERSION + 1):
            if v in _MIGRATIONS:
                self._conn.executescript(_MIGRATIONS[v])
                self._conn.execute("UPDATE schema_version SET version=? WHERE version=?", (v, v - 1))
                self._conn.commit()
                log.info("Applied schema migration -> v%s", v)

    def close(self) -> None:
        self._conn.close()

    # ------------------------------------------------------------------ #
    # episodes
    # ------------------------------------------------------------------ #
    def upsert_episode(self, ep: Episode) -> int:
        def _do(conn: sqlite3.Connection) -> int:
            conn.execute(
                """
                INSERT INTO episodes (spotify_id, url, title, show_name, publisher,
                                      rss_url, audio_url, duration_seconds, state,
                                      confidence, reason, candidates, parsed_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(url) DO UPDATE SET
                    spotify_id=excluded.spotify_id,
                    title=excluded.title,
                    show_name=excluded.show_name,
                    publisher=excluded.publisher,
                    rss_url=excluded.rss_url,
                    audio_url=excluded.audio_url,
                    duration_seconds=excluded.duration_seconds,
                    state=excluded.state,
                    confidence=excluded.confidence,
                    reason=excluded.reason,
                    candidates=excluded.candidates,
                    parsed_at=excluded.parsed_at
                """,
                (
                    ep.spotify_id,
                    ep.url,
                    ep.title,
                    ep.show_name,
                    ep.publisher,
                    ep.rss_url,
                    ep.audio_url,
                    ep.duration_seconds,
                    ep.state,
                    ep.confidence,
                    ep.reason,
                    json.dumps(ep.candidates) if ep.candidates else None,
                    ep.parsed_at or _now(),
                ),
            )
            return conn.execute("SELECT id FROM episodes WHERE url=?", (ep.url,)).fetchone()["id"]

        return self._write(_do)

    def get_episode(self, episode_id: int) -> Optional[Episode]:
        row = self._conn.execute("SELECT * FROM episodes WHERE id=?", (episode_id,)).fetchone()
        return Episode.from_row(row) if row else None

    def get_episode_by_url(self, url: str) -> Optional[Episode]:
        row = self._conn.execute("SELECT * FROM episodes WHERE url=?", (url,)).fetchone()
        return Episode.from_row(row) if row else None

    def find_episodes(self, query: str, limit: int = 20) -> List[Episode]:
        like = f"%{query}%"
        rows = self._conn.execute(
            """
            SELECT * FROM episodes
            WHERE title LIKE ? OR show_name LIKE ? OR url LIKE ?
            ORDER BY parsed_at DESC LIMIT ?
            """,
            (like, like, like, limit),
        ).fetchall()
        return [Episode.from_row(r) for r in rows]

    def set_episode_state(self, episode_id: int, state: str, confidence: Optional[float],
                          reason: str, audio_url: Optional[str] = None) -> None:
        def _do(conn: sqlite3.Connection) -> None:
            conn.execute(
                "UPDATE episodes SET state=?, confidence=?, reason=?, audio_url=? WHERE id=?",
                (state, confidence, reason, audio_url, episode_id),
            )

        self._write(_do)

    def set_episode_audio_url(self, episode_id: int, audio_url: str) -> None:
        """Point an episode at a (new) audio source, e.g. after a download."""

        def _do(conn: sqlite3.Connection) -> None:
            conn.execute(
                "UPDATE episodes SET audio_url=? WHERE id=?", (audio_url, episode_id)
            )

        self._write(_do)

    # ------------------------------------------------------------------ #
    # jobs
    # ------------------------------------------------------------------ #
    def create_job(self, episode_id: int, model: Optional[str] = None,
                   chunk_minutes: Optional[float] = None) -> Job:
        now = _now()

        def _do(conn: sqlite3.Connection) -> int:
            cur = conn.execute(
                """
                INSERT INTO jobs (episode_id, status, model, chunk_minutes, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (episode_id, JOB_PENDING, model, chunk_minutes, now, now),
            )
            return cur.lastrowid

        job_id = self._write(_do)
        job = self.get_job(job_id)
        assert job is not None
        return job

    def list_jobs(self, limit: int = 50) -> List[Job]:
        rows = self._conn.execute(
            "SELECT * FROM jobs ORDER BY id DESC LIMIT ?", (limit,)
        ).fetchall()
        return [Job.from_row(r) for r in rows]

    def get_job(self, job_id: int) -> Optional[Job]:
        row = self._conn.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone()
        return Job.from_row(row) if row else None

    def update_job(self, job_id: int, *, status: Optional[str] = None, error: Optional[str] = None,
                   chunk_count: Optional[int] = None) -> None:
        now = _now()
        sets = ["updated_at=?"]
        params: List[Any] = [now]
        if status is not None:
            sets.append("status=?")
            params.append(status)
        if error is not None:
            sets.append("error=?")
            params.append(error)
        if chunk_count is not None:
            sets.append("chunk_count=?")
            params.append(chunk_count)
        params.append(job_id)

        def _do(conn: sqlite3.Connection) -> None:
            conn.execute(f"UPDATE jobs SET {', '.join(sets)} WHERE id=?", params)

        self._write(_do)

    def has_active_job(self) -> bool:
        placeholders = ",".join("?" * len(ACTIVE_STATUSES))
        row = self._conn.execute(
            f"SELECT COUNT(*) AS c FROM jobs WHERE status IN ({placeholders})",
            ACTIVE_STATUSES,
        ).fetchone()
        return row["c"] > 0

    def active_jobs(self) -> List[Job]:
        placeholders = ",".join("?" * len(ACTIVE_STATUSES))
        rows = self._conn.execute(
            f"SELECT * FROM jobs WHERE status IN ({placeholders}) ORDER BY id",
            ACTIVE_STATUSES,
        ).fetchall()
        return [Job.from_row(r) for r in rows]

    def claim_job(self, job_id: int) -> bool:
        """Atomically transition a PENDING job to RUNNING.

        Returns True if this call won the claim (row was PENDING), False if the
        job is already RUNNING/claimed, terminal, or missing.  The transition is
        a single conditional UPDATE inside one transaction, so two concurrent
        processes claiming the same job cannot both win (the loser matches zero
        rows).  Raises sqlite3.IntegrityError if another *different* job is
        already active (partial unique index on jobs.status).
        """

        def _do(conn: sqlite3.Connection) -> bool:
            cur = conn.execute(
                "UPDATE jobs SET status=?, updated_at=? WHERE id=? AND status=?",
                (JOB_RUNNING, _now(), job_id, JOB_PENDING),
            )
            return cur.rowcount == 1

        return self._write(_do)

    # ------------------------------------------------------------------ #
    # transcripts & segments
    # ------------------------------------------------------------------ #
    def upsert_transcript(self, job_id: int, episode_id: int, language: str) -> int:
        def _do(conn: sqlite3.Connection) -> int:
            conn.execute(
                """
                INSERT INTO transcripts (job_id, episode_id, language, segments, created_at)
                VALUES (?, ?, ?, 0, ?)
                ON CONFLICT(job_id) DO UPDATE SET language=excluded.language
                """,
                (job_id, episode_id, language, _now()),
            )
            row = conn.execute("SELECT id FROM transcripts WHERE job_id=?", (job_id,)).fetchone()
            return row["id"]

        return self._write(_do)

    def get_transcript(self, job_id: int) -> Optional[Transcript]:
        row = self._conn.execute("SELECT * FROM transcripts WHERE job_id=?", (job_id,)).fetchone()
        return Transcript.from_row(row) if row else None

    def segments_for_job(self, job_id: int) -> List[Dict[str, Any]]:
        rows = self._conn.execute(
            "SELECT * FROM segments WHERE job_id=? ORDER BY chunk_index, start_time",
            (job_id,),
        ).fetchall()
        return [dict(r) for r in rows]

    def add_segment(self, job_id: int, tx_id: int, chunk_index: int,
                    start_time: float, end_time: float, text: str) -> None:
        def _do(conn: sqlite3.Connection) -> None:
            conn.execute(
                """
                INSERT INTO segments (transcript_id, job_id, chunk_index, start_time, end_time, text)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (tx_id, job_id, chunk_index, start_time, end_time, text),
            )
            conn.execute("UPDATE transcripts SET segments=segments+1 WHERE id=?", (tx_id,))

        self._write(_do)

    def delete_segments_for_chunk(self, job_id: int, chunk_index: int) -> int:
        """Remove all segments recorded for a chunk (resume idempotency).

        Re-transcribing a chunk whose 'done' checkpoint was never written must
        not accumulate duplicates.  Deletes the stale rows and decrements the
        owning transcript's segment count accordingly.  Returns the number of
        rows removed.
        """

        def _do(conn: sqlite3.Connection) -> int:
            tx = conn.execute(
                "SELECT id FROM transcripts WHERE job_id=?", (job_id,)
            ).fetchone()
            if tx is None:
                return 0
            cur = conn.execute(
                "DELETE FROM segments WHERE job_id=? AND chunk_index=?",
                (job_id, chunk_index),
            )
            removed = cur.rowcount
            if removed:
                conn.execute(
                    "UPDATE transcripts SET segments=MAX(0, segments-?) WHERE id=?",
                    (removed, tx["id"]),
                )
            return removed

        return self._write(_do)

    # ------------------------------------------------------------------ #
    # checkpoints
    # ------------------------------------------------------------------ #
    def get_checkpoint(self, job_id: int, chunk_index: int) -> Optional[Dict[str, Any]]:
        row = self._conn.execute(
            "SELECT * FROM checkpoints WHERE job_id=? AND chunk_index=?",
            (job_id, chunk_index),
        ).fetchone()
        if row is None:
            return None
        out = dict(row)
        if out.get("result"):
            try:
                out["result"] = json.loads(out["result"])
            except (json.JSONDecodeError, TypeError):
                out["result"] = None
        return out

    def set_checkpoint(self, job_id: int, chunk_index: int, status: str,
                       audio_path: Optional[str] = None, result: Optional[Dict[str, Any]] = None) -> None:
        def _do(conn: sqlite3.Connection) -> None:
            conn.execute(
                """
                INSERT INTO checkpoints (job_id, chunk_index, status, audio_path, result, updated_at)
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(job_id, chunk_index) DO UPDATE SET
                    status=excluded.status, result=excluded.result, updated_at=excluded.updated_at
                """,
                (job_id, chunk_index, status, audio_path,
                 json.dumps(result) if result is not None else None, _now()),
            )

        self._write(_do)

    def checkpoints_for_job(self, job_id: int) -> List[Dict[str, Any]]:
        rows = self._conn.execute(
            "SELECT * FROM checkpoints WHERE job_id=? ORDER BY chunk_index", (job_id,)
        ).fetchall()
        return [dict(r) for r in rows]