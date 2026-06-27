"""In-memory sliding-window rate limiter.

Used to throttle login attempts per client IP, complementing the per-account
lockout (which a distributed attack across many accounts could otherwise evade).

This implementation is process-local and intended for a single instance or
development. A multi-instance deployment should back the same interface with a
shared store (e.g. Redis); the limiter is deliberately small and injectable so
that swap is straightforward.
"""

from __future__ import annotations

import threading
import time
from collections import defaultdict, deque


class SlidingWindowRateLimiter:
    """Counts events per key within a sliding time window."""

    def __init__(self, *, max_events: int, window_seconds: float) -> None:
        if max_events < 1:
            msg = "max_events must be >= 1"
            raise ValueError(msg)
        if window_seconds <= 0:
            msg = "window_seconds must be > 0"
            raise ValueError(msg)
        self._max_events = max_events
        self._window = window_seconds
        self._events: dict[str, deque[float]] = defaultdict(deque)
        self._lock = threading.Lock()

    def _evict(self, key: str, now: float) -> None:
        bucket = self._events[key]
        cutoff = now - self._window
        while bucket and bucket[0] <= cutoff:
            bucket.popleft()
        if not bucket:
            self._events.pop(key, None)

    def is_blocked(self, key: str, *, now: float | None = None) -> bool:
        """Whether the key has reached the limit within the current window."""
        moment = time.monotonic() if now is None else now
        with self._lock:
            self._evict(key, moment)
            return len(self._events[key]) >= self._max_events if key in self._events else False

    def record(self, key: str, *, now: float | None = None) -> None:
        """Record one event for the key."""
        moment = time.monotonic() if now is None else now
        with self._lock:
            self._evict(key, moment)
            self._events[key].append(moment)

    def reset(self, key: str) -> None:
        """Clear all recorded events for a key (e.g. on successful login)."""
        with self._lock:
            self._events.pop(key, None)
