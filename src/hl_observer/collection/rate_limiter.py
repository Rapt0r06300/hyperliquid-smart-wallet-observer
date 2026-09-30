from __future__ import annotations

from dataclasses import dataclass, field
from collections import deque


@dataclass(slots=True)
class WindowRateLimiter:
    """Sliding-window limiter for one read-only egress shard."""

    max_requests: int = 25
    window_seconds: float = 10.0
    _events: deque[float] = field(default_factory=deque)

    def reserve(self, now_seconds: float) -> tuple[bool, float]:
        self._drop_old(now_seconds)
        if len(self._events) < max(1, int(self.max_requests)):
            self._events.append(float(now_seconds))
            return True, 0.0
        wait = self.window_seconds - (float(now_seconds) - self._events[0])
        return False, max(0.0, wait)

    def remaining(self, now_seconds: float) -> int:
        self._drop_old(now_seconds)
        return max(0, int(self.max_requests) - len(self._events))

    def _drop_old(self, now_seconds: float) -> None:
        cutoff = float(now_seconds) - max(0.001, float(self.window_seconds))
        while self._events and self._events[0] <= cutoff:
            self._events.popleft()
