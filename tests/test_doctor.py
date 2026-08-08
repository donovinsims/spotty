"""Phase 4 tests for `pt doctor` preflight checks.

The CLI smoke test runs the real checks against a tmp data dir (offline: the
DB is empty, ffmpeg/tailscale/launchd are read-only probes of this machine).
Unit tests monkeypatch individual checks/helpers to force FAIL/WARN outcomes.
"""

from __future__ import annotations

import io

import pytest

from podcast_transcriber import cli
from podcast_transcriber import doctor
from podcast_transcriber.config import Config
from podcast_transcriber.store import JOB_RUNNING, Episode


@pytest.fixture(autouse=True)
def _isolate_cfg(monkeypatch, tmp_path):
    monkeypatch.setattr(cli, "get_config", lambda: Config(data_dir=str(tmp_path / "data")))
    yield


def test_doctor_cli_smoke_runs_and_returns_zero(tmp_path):
    """At minimum: `pt doctor` runs without crashing and exits 0 on this
    machine (all FAIL-causing resources are present: ffmpeg, disk, tailscale
    CLI, DB opens)."""
    assert cli.main(["doctor"]) == 0


def test_doctor_prints_every_section(tmp_path, capsys):
    cli.main(["doctor"])
    out = capsys.readouterr().out
    for section in ("Python & venv", "ffmpeg", "Data dir", ".env", "Database",
                    "Worker state", "Tailscale", "launchd", "Model cache"):
        assert section in out, f"missing section {section!r}"
    assert "summary:" in out
    assert "doctor v" in out


def test_doctor_masks_auth_token(monkeypatch, tmp_path, capsys):
    monkeypatch.setenv("PT_AUTH_TOKEN", "super-secret-token-value")
    cli.main(["doctor"])
    out = capsys.readouterr().out
    assert "super-secret-token-value" not in out
    assert "PT_AUTH_TOKEN=<set, masked>" in out


def test_doctor_exit_1_on_fail(monkeypatch, tmp_path, capsys):
    monkeypatch.setattr(doctor, "check_ffmpeg",
                        lambda: (doctor.FAIL, "fake missing ffmpeg"))
    cfg = Config(data_dir=str(tmp_path / "data"))
    rc = doctor.run_checks(cfg)
    assert rc == 1
    out = capsys.readouterr().out
    assert "[FAIL] ffmpeg / ffprobe: fake missing ffmpeg" in out
    assert "1 fail" in out


def test_doctor_warn_does_not_fail(monkeypatch, tmp_path, capsys):
    monkeypatch.setattr(doctor, "check_launchd",
                        lambda: (doctor.WARN, "service not loaded"))
    cfg = Config(data_dir=str(tmp_path / "data"))
    rc = doctor.run_checks(cfg)
    assert rc == 0


def test_doctor_low_disk_is_fail(monkeypatch, tmp_path, capsys):
    import shutil

    class LowDisk:
        free = 100 * 1024  # far below 1 GiB
        used = 0
        total = 100 * 1024

    monkeypatch.setattr(shutil, "disk_usage", lambda path: LowDisk())
    cfg = Config(data_dir=str(tmp_path / "data"))
    rc = doctor.run_checks(cfg)
    assert rc == 1
    out = capsys.readouterr().out
    assert "[FAIL] Data dir & disk" in out
    assert "GiB free" in out


def test_doctor_reports_running_jobs_as_warn(monkeypatch, tmp_path, capsys):
    cfg = Config(data_dir=str(tmp_path / "data"))
    cfg.ensure_dirs()
    store = doctor.Store(str(cfg.db_path))
    eid = store.upsert_episode(Episode(url="https://x/ep/dr", title="Dr"))
    store.create_job(eid)
    store.update_job(store.list_jobs()[0].id, status=JOB_RUNNING)
    store.close()
    rc = doctor.run_checks(cfg)
    assert rc == 0  # a RUNNING job is a WARN, not a FAIL
    out = capsys.readouterr().out
    assert "[WARN] Worker state" in out
    assert "RUNNING" in out


def test_doctor_db_broken_is_fail(monkeypatch, tmp_path, capsys):
    """A Store that cannot open must be a FAIL (not a crash)."""
    cfg = Config(data_dir=str(tmp_path / "data"))
    cfg.ensure_dirs()
    # Point the DB at a path that cannot be created (a FILE where a dir is needed).
    blocker = tmp_path / "blocker"
    blocker.write_text("x")
    cfg.db_path = blocker / "sub" / "nested.db"
    rc = doctor.run_checks(cfg)
    assert rc == 1
    out = capsys.readouterr().out
    assert "[FAIL] Database" in out


def test_doctor_check_raises_becomes_fail(monkeypatch, tmp_path, capsys):
    def explode():
        raise RuntimeError("boom")

    monkeypatch.setattr(doctor, "check_python", explode)
    cfg = Config(data_dir=str(tmp_path / "data"))
    rc = doctor.run_checks(cfg)
    assert rc == 1
    out = capsys.readouterr().out
    assert "[FAIL] Python & venv" in out
    assert "boom" in out
