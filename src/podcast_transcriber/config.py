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
HOST_ENV = "PT_HOST"
PORT_ENV = "PT_PORT"
AUTH_TOKEN_ENV = "PT_AUTH_TOKEN"
RATE_LIMIT_ENV = "PT_RATE_LIMIT_PER_MIN"
MAX_QUEUED_ENV = "PT_MAX_QUEUED"
TRUST_PROXY_ENV = "PT_TRUST_PROXY"

# HuggingFace has no `mlx-community/whisper-small`; the mlx-converted repo is
# `mlx-community/whisper-small-mlx`.
DEFAULT_MODEL = "mlx-community/whisper-small-mlx"
DEFAULT_DATA_DIR = "data"
DEFAULT_TOP_RESULTS = 25
DEFAULT_DURATION_TOLERANCE = 600.0  # seconds
DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8765
DEFAULT_RATE_LIMIT = 10    # POST /jobs per client IP per minute
DEFAULT_MAX_QUEUED = 50    # PENDING + QUEUED jobs allowed before rejecting
DEFAULT_TRUST_PROXY = False

#: Host values considered "loopback" (cookie Secure stays off so plain-HTTP
#: local use keeps working).
LOOPBACK_HOSTS = ("127.0.0.1", "localhost", "::1")

_CHUNK_MINUTES_ENV = "PT_CHUNK_MINUTES"
DEFAULT_CHUNK_MINUTES = 10.0

_WORKER_STOP_TIMEOUT_ENV = "PT_WORKER_STOP_TIMEOUT"
DEFAULT_WORKER_STOP_TIMEOUT = 5.0


def load_env() -> None:
    """Load `.env` (if present) into the environment. Idempotent-ish.

    We prefer a `.env` at the repository/package root (so `pt` works from any
    CWD), then fall back to the current working directory.
    """
    root_env = Path(__file__).resolve().parents[2] / ".env"
    load_dotenv(root_env, override=False)
    load_dotenv(os.path.join(os.getcwd(), ".env"), override=False)


def is_loopback_host(host: Optional[str]) -> bool:
    """True when ``host`` is a loopback address (127.0.0.1 / localhost / ::1).

    Used to decide cookie ``Secure`` behaviour and whether to warn about
    serving unauthenticated on an exposed interface.
    """
    return (host or "").strip().lower() in LOOPBACK_HOSTS


def _as_bool(value) -> bool:
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in ("1", "true", "yes", "on")


class Config:
    """Configuration snapshot used throughout the package."""

    def __init__(
        self,
        model: Optional[str] = None,
        data_dir: Optional[str] = None,
        top_results: Optional[int] = None,
        duration_tolerance: Optional[float] = None,
        chunk_minutes: Optional[float] = None,
        worker_stop_timeout: Optional[float] = None,
        host: Optional[str] = None,
        port: Optional[int] = None,
        auth_token: Optional[str] = None,
        rate_limit: Optional[int] = None,
        max_queued: Optional[int] = None,
        trust_proxy: Optional[bool] = None,
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
        self.worker_stop_timeout = float(
            worker_stop_timeout
            if worker_stop_timeout is not None
            else os.getenv(_WORKER_STOP_TIMEOUT_ENV, DEFAULT_WORKER_STOP_TIMEOUT)
        )
        # Web UI bind address (Phase 3; also read by the ops scripts).
        self.host = host or os.getenv(HOST_ENV, DEFAULT_HOST)
        self.port = int(port if port is not None else os.getenv(PORT_ENV, DEFAULT_PORT))
        # Optional single-user auth token; empty string / unset disables auth.
        raw_token = auth_token if auth_token is not None else os.getenv(AUTH_TOKEN_ENV, "")
        self.auth_token = (raw_token or None)
        # Phase 4: POST /jobs per-IP rate limit + queue cap + proxy trust.
        self.rate_limit = int(
            rate_limit if rate_limit is not None else os.getenv(RATE_LIMIT_ENV, DEFAULT_RATE_LIMIT)
        )
        self.max_queued = int(
            max_queued if max_queued is not None else os.getenv(MAX_QUEUED_ENV, DEFAULT_MAX_QUEUED)
        )
        self.trust_proxy = _as_bool(
            trust_proxy if trust_proxy is not None else os.getenv(TRUST_PROXY_ENV, DEFAULT_TRUST_PROXY)
        )

    def ensure_dirs(self) -> Path:
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.audio_dir.mkdir(parents=True, exist_ok=True)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        return self.data_dir


def get_config() -> Config:
    load_env()
    return Config()