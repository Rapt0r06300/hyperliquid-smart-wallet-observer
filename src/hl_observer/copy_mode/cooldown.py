"""Fill cooldown (V12, repo 04): block duplicate copies of the same signal within a window."""

from __future__ import annotations


class FillCooldown:
    def __init__(self, *, window_ms: int = 5_000) -> None:
        self.window_ms = max(0, int(window_ms))
        self._last: dict[str, int] = {}

    def allow(self, key: str, *, now_ms: int) -> bool:
        """True if this key hasn't fired within the cooldown window. Records the fire on allow."""
        last = self._last.get(key)
        if last is not None and (int(now_ms) - last) < self.window_ms:
            return False
        self._last[key] = int(now_ms)
        return True


__all__ = ["FillCooldown"]
