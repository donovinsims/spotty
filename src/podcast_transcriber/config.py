"""Environment-driven configuration.

Reads `.env` (via python-dotenv) then overrides with real environment
variables.  Defaults:
  * PT_MODEL     -> mlx-community/whisper-small
  * PT_DATA_DIR  -> data/  (relative to the current working directory)
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Mapping, Optional

from dotenv import load_dotenv

#: Env vars we honour.
MODEL_ENV = "PT_MODEL"
DATA_DIR_ENV = "PT_DATA_DIR"
TOP_LISTENERS_ENV = "PT_TOP_RESULTS"
DURATION_TOLERANCE_ENV = "PT_DURATION_TOLERANCE"

# HuggingFace has no `mlx-community/whisper-small`; the mlx-converted repo is
# `mlx-community/whisper-small-mlx`.
DEFAULT_MODEL = "mlx-community/whisper-small-mlx"
DEFAULT_DATA_DIR = "data"
DEFAULT_TOP_RESULTS = 25
DEFAULT_DURATION_TOLERANCE = 600.0  # seconds

_CHUNK_MINUTES_ENV = "PT_CHUNK_MINUTES"
DEFAULT_CHUNK_MINUTES = 10.0


def load_env() -> None:
    """Load `.env` (if present) into the environment. Idempotent-ish."""
    load_dotenv(os.path.join(os.getcwd(), ".env"), override=False)


class Config:
    """Configuration snapshot used throughout the package."""

    def __init__(
        self,
        model: Optional[str] = None,
        data_dir: Optional[str] = None,
        top_results: Optional[int] = None,
        duration_tolerance: Optional[float] = None,
        chunk_minutes: Optional[float] = None,
    ) -> None:
        self.model = model or os.getenv(MODEL_ENV, DEFAULT_MODEL)
        data_dir = data_dir or os.getenv(DATA_DIR_ENV, DEFAULT_DATA_DIR)
        self.data_dir = Path(data_dir)
        self.db_path = self.data_dir / "podcast_transcriber.db"
        self.audio_dir = self.data_dir / "audio"
        self.cache_dir = self.data_dir / "cache"
        self.top_results = int(
            top_results if top_results is not None else os.getenv(TOP_LISTENERS_ENV, DEFAULT_TOP_RESULTS)
        )
        self.duration_tolerance = float(
            duration_tolerance
            if duration_tolerance is not None
            else os.getenv(DURATION_TOLERANCE_ENV, DEFAULT_DURATION_TOLERANCE)
        )
        self.chunk_minutes = float(
            chunk_minutes if chunk_minutes is not None else os.getenv(_CHUNK_MINUTES_ENV, DEFAULT_CHUNK_MINUTES)
        )

    def ensure_dirs(self) -> Path:
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.audio_dir.mkdir(parents=True, exist_ok=True)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        return self.data_dir


def get_config() -> Config:
    load_env()
    return Config()