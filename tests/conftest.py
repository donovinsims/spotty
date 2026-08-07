"""Shared pytest fixtures."""

from __future__ import annotations

import pytest

from podcast_transcriber.store import Store


@pytest.fixture()
def store(tmp_path):
    db = tmp_path / "test.db"
    s = Store(db)
    yield s
    s.close()