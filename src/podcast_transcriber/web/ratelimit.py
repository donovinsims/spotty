"""Per-client-IP sliding-window rate limiter for POST /jobs (Phase 4).

Pure stdlib (``collections.deque`` + ``threading.Lock``) -- this app is a
single-process worker, so an in-memory dict is all that is needed.  The window
is sliding: hits older than ``window_seconds`` are pruned on every call.

``allow(key)`` returns ``(True, 0)`` when the caller may proceed, or
``(False, retry_after_seconds)`` when the per-window limit is exhausted.
"""

from __future__ import annotations

import threading
import time
from collections import deque
from typing import Deque, Dict, Tuple

#: Deque of hit timestamps per key (monotonic seconds).
_Hits = Deque[float]


class SlidingWindowLimiter:
    """Per-key sliding-window limiter (keys are client IPs)."""

    def __init__(self, limit_per_min: int = 10, window_seconds: float = 60.0) -> None:
        # Explicit 0 is clamped to 1 (a zero allowance would block everything
        # forever); None means "use the default".
        self.limit = max(1, int(limit_per_min if limit_per_min is not None else 10))
        self.window = max(1.0, float(window_seconds))
        self._hits: Dict[str, _Hits] = {}
        self._lock = threading.Lock()

    def allow(self, key: str) -> Tuple[bool, int]:
        """Record a hit for ``key``; True if it fits within the window.

        On False, the second return value is a Retry-After hint in whole
        seconds (never less than 1).
        """
        now = time.monotonic()
        cutoff = now - self.window
        with self._lock:
            hits = self._hits.setdefault(key, deque())
            while hits and hits[0] <= cutoff:
                hits.popleft()
            if len(hits) >= self.limit:
                retry_after = max(1, int(self.window - (now - hits[0])) + 1)
                return False, retry_after
            hits.append(now)
            return True, 0

    def clear(self) -> None:
        """Drop all recorded hits (used by tests)."""
        with self._lock:
            self._hits.clear()
