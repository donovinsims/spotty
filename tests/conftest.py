"""Shared pytest fixtures."""

from __future__ import annotations

import os

import pytest

from podcast_transcriber.store import Store


@pytest.fixture(autouse=True)
def _no_env_leak(monkeypatch):
    """Keep the repo .env out of the process environment for every test.

    cli.main() / transcribe_job() call get_config() -> load_env(), which loads
    the repo .env into os.environ permanently (load_dotenv, override=False).
    That leaks PT_AUTH_TOKEN (and other PT_*) into every later Config(), e.g.
    flipping auth ON for tests that expect 200/4xx and turning them into 401s.
    Delete all PT_* before each test; monkeypatch restores the original state
    afterwards, so any re-pollution inside a test is undone at teardown.
    """

    for key in [k for k in os.environ if k.startswith("PT_")]:
        monkeypatch.delenv(key, raising=False)


@pytest.fixture()
def store(tmp_path):
    db = tmp_path / "test.db"
    s = Store(db)
    yield s
    s.close()