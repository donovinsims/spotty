"""In-process background worker for the Phase 2 web UI.

A single daemon thread per database processes waiting jobs (QUEUED and PENDING)
oldest-first.  The single-active-job rule stays exactly as Phase 1 defined it:

  * the DB partial unique index on jobs(status) WHERE status IN ('PENDING',
    'RUNNING') allows at most ONE active job at a time;
  * jobs created while the slot is taken are stored as QUEUED (an additive
    status invisible to that index);
  * this worker promotes QUEUED -> PENDING -> RUNNING (via transcribe_job's own
    claim) strictly in creation order, so a second POST /jobs stays queued until
    the first job finishes.

Only one worker exists per database (module-level registry), and the worker
creates its own sqlite3 Store inside its own thread (sqlite3 connections are
not thread-safe across threads).

Download + transcription call the exact Phase 1 functions
(download_episode / transcribe_job); nothing is re-implemented here.
"""

from __future__ import annotations

import logging
import sqlite3
import threading
from pathlib import Path
from typing import Callable, Dict, Optional

from ..config import Config
from ..download import DownloadError, download_episode
from ..store import JOB_FAILED, JOB_PENDING, JOB_QUEUED, Store
from ..transcribe import TranscribeError, transcribe_job

log = logging.getLogger(__name__)

#: job_id -> last progress line, for the status fragment.
PROGRESS: Dict[int, str] = {}
_progress_lock = threading.Lock()

#: module-level worker registry: resolved db path -> Worker (one per database).
_registry: Dict[str, "Worker"] = {}
_registry_lock = threading.Lock()


def _set_progress(job_id: int, line: str) -> None:
    with _progress_lock:
        PROGRESS[job_id] = line


def progress_for(job_id: int) -> Optional[str]:
    with _progress_lock:
        return PROGRESS.get(job_id)


class Worker:
    """One background processing thread per database."""

    def __init__(
        self,
        db_path,
        cfg: Config,
        *,
        download_func: Callable = download_episode,
        transcribe_func: Callable = transcribe_job,
    ) -> None:
        self._db_path = str(Path(db_path))
        self._cfg = cfg
        self._download_func = download_func
        self._transcribe_func = transcribe_func
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None
        # The worker's own Store is created lazily INSIDE the worker thread so
        # the sqlite3 connection belongs to the thread that uses it.
        self._store: Optional[Store] = None

    # ------------------------------------------------------------------ #
    # lifecycle
    # ------------------------------------------------------------------ #
    @property
    def running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def start(self) -> None:
        if self.running:
            return
        self._stop.clear()
        self._thread = threading.Thread(
            target=self._run, name="pt-web-worker", daemon=True
        )
        self._thread.start()
        log.info("web worker started for %s", self._db_path)

    def stop(self, timeout: float = 3.0) -> None:
        self._stop.set()
        if self._thread is not None and self._thread.is_alive():
            self._thread.join(timeout=timeout)
        self._thread = None

    # ------------------------------------------------------------------ #
    # main loop
    # ------------------------------------------------------------------ #
    def _run(self) -> None:
        self._store = Store(self._db_path)  # connection owned by this thread
        log.info("web worker loop running for %s", self._db_path)
        while not self._stop.is_set():
            try:
                job = self._store.next_queued_job()
            except Exception:  # noqa: BLE001 - never kill the loop
                log.exception("worker query failed")
                self._stop.wait(1.0)
                continue
            if job is None:
                self._stop.wait(1.0)
                continue
            if job.status == JOB_QUEUED:
                try:
                    self._store.promote_queued_job(job.id)  # type: ignore[arg-type]
                except sqlite3.IntegrityError:
                    # Slot still busy (another job is PENDING/RUNNING): wait.
                    self._stop.wait(1.0)
                continue  # loop immediately: pick the promoted job as PENDING
            try:
                self._process(job.id)
            except Exception:  # noqa: BLE001 - _process already marks FAILED
                log.exception("worker failed processing job %s", job.id)
                self._stop.wait(0.5)
            # A PENDING job that could not be claimed (another job is active)
            # must be retried, but not in a hot loop: back off.
            current = self._store.get_job(job.id)
            if current is not None and current.status == JOB_PENDING:
                self._stop.wait(1.0)
        log.info("web worker loop stopped for %s", self._db_path)

    def _process(self, job_id: int) -> None:
        """Run download + transcribe for one PENDING job.

        transcribe_job claims PENDING -> RUNNING itself and enforces the
        single-active-job guard, so if the slot was taken by an external
        process it raises TranscribeError and the job stays PENDING for a
        later retry.  Terminal failures are recorded on the job row.
        """
        store = self._store
        assert store is not None

        def progress(line: str) -> None:
            _set_progress(job_id, line)
            log.info("job %s: %s", job_id, line)

        try:
            episode = store.get_episode(store.get_job(job_id).episode_id)  # type: ignore[union-attr]
            if episode is None:
                store.update_job(job_id, status=JOB_FAILED, error="episode missing")
                return
            if episode.audio_url:
                # Downloading also sets the local path + verifies it decodes;
                # it is skipped entirely when audio_url is already a local file.
                self._download_func(
                    store, episode.id,  # type: ignore[arg-type]
                    self._cfg.audio_dir,
                    progress=progress,
                )
            self._transcribe_func(
                store,
                job_id,
                model=self._cfg.model,
                chunk_minutes=self._cfg.chunk_minutes,
                progress=progress,
            )
        except TranscribeError:
            # transcribe_job marks the job FAILED for chunk failures, but the
            # "another job is active / already claimed" guard errors leave the
            # job PENDING -- in that case the loop simply retries it later.
            current = store.get_job(job_id)
            if current is not None and current.status == JOB_FAILED:
                log.info("job %s failed", job_id)
        except DownloadError as exc:
            store.update_job(job_id, status=JOB_FAILED, error=str(exc))
            log.info("job %s download failed: %s", job_id, exc)
        except Exception as exc:  # noqa: BLE001 - surface a clear error
            store.update_job(job_id, status=JOB_FAILED, error=str(exc))
            log.exception("job %s failed", job_id)


def get_worker(db_path, cfg: Config, **kwargs) -> Worker:
    """Return the single Worker for a database, creating it on first use."""
    key = str(Path(db_path).resolve())
    with _registry_lock:
        worker = _registry.get(key)
        if worker is None:
            worker = Worker(db_path, cfg, **kwargs)
            _registry[key] = worker
        return worker


def stop_worker(db_path) -> None:
    key = str(Path(db_path).resolve())
    with _registry_lock:
        worker = _registry.pop(key, None)
    if worker is not None:
        worker.stop()


def stop_all() -> None:
    with _registry_lock:
        workers = list(_registry.values())
        _registry.clear()
    for w in workers:
        w.stop()
