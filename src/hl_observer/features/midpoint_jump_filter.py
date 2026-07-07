"""Midpoint jump filter (V12, repo 04 LP-tool): block a signal on a suspicious mid jump.

A sudden midpoint jump beyond a bps threshold between consecutive ticks is usually noise /
a bad print, not a real move — copying it degrades the edge. Pure / deterministic.
"""

from __future__ import annotations


def midpoint_jump_bps(prev_mid: float | None, new_mid: float | None) -> float | None:
    if prev_mid is None or new_mid is None or prev_mid <= 0:
        return None
    return abs(new_mid - prev_mid) / prev_mid * 10_000.0


def is_midpoint_jump(prev_mid: float | None, new_mid: float | None, *, max_jump_bps: float = 50.0) -> bool:
    j = midpoint_jump_bps(prev_mid, new_mid)
    return j is not None and j > float(max_jump_bps)


class MidpointJumpFilter:
    def __init__(self, *, max_jump_bps: float = 50.0) -> None:
        self.max_jump_bps = float(max_jump_bps)
        self._last: float | None = None

    def accept(self, mid: float | None) -> bool:
        """True if the tick is acceptable (no abnormal jump). Updates state."""
        if mid is None:
            return False
        blocked = is_midpoint_jump(self._last, mid, max_jump_bps=self.max_jump_bps)
        self._last = float(mid)
        return not blocked


__all__ = ["midpoint_jump_bps", "is_midpoint_jump", "MidpointJumpFilter"]
