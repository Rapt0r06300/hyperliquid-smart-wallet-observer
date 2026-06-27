"""Mid stability / stable confirmation (V12, repo 04): require N stable ticks.

A signal is only confirmed once the mid has stayed within a tolerance for N consecutive
ticks — avoids acting on a single flickering print. Pure / deterministic.
"""

from __future__ import annotations

from collections import deque


class MidStability:
    def __init__(self, *, window: int = 3, tol_bps: float = 5.0) -> None:
        self.window = max(2, int(window))
        self.tol_bps = float(tol_bps)
        self._mids: deque[float] = deque(maxlen=self.window)

    def push(self, mid: float | None) -> None:
        if mid is not None:
            self._mids.append(float(mid))

    def is_stable(self) -> bool:
        if len(self._mids) < self.window:
            return False
        lo, hi = min(self._mids), max(self._mids)
        if lo <= 0:
            return False
        return (hi - lo) / lo * 10_000.0 <= self.tol_bps


def requires_stable_confirmation(mids: list[float], *, window: int = 3, tol_bps: float = 5.0) -> bool:
    s = MidStability(window=window, tol_bps=tol_bps)
    for m in mids:
        s.push(m)
    return s.is_stable()


__all__ = ["MidStability", "requires_stable_confirmation"]
