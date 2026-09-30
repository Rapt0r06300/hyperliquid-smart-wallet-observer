from __future__ import annotations

import time
from collections.abc import Callable


class LocalRateLimiter:
    """Tiny local rate limiter used to avoid request bursts in read-only mode."""

    def __init__(
        self,
        min_interval_ms: int,
        *,
        clock: Callable[[], float] | None = None,
        sleeper: Callable[[float], None] | None = None,
    ):
        self.min_interval_seconds = max(0.0, min_interval_ms / 1000.0)
        self._clock = clock or time.monotonic
        self._sleeper = sleeper or time.sleep
        self._last_request_at: float | None = None

    def wait(self) -> None:
        if self.min_interval_seconds <= 0:
            self._last_request_at = self._clock()
            return
        now = self._clock()
        if self._last_request_at is not None:
            elapsed = now - self._last_request_at
            remaining = self.min_interval_seconds - elapsed
            if remaining > 0:
                self._sleeper(remaining)
                now = self._clock()
        self._last_request_at = now
