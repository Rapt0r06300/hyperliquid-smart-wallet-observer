"""EMA / median smoother (V12, repo 04): smooth REAL inputs, never invent a price.

Output is a deterministic function of the real values pushed in (EMA blended with a rolling
median). It NEVER fabricates a value when there is no input. Pure.
"""

from __future__ import annotations

from collections import deque
from statistics import median


class EmaMedianSmoother:
    def __init__(self, *, alpha: float = 0.3, median_window: int = 5) -> None:
        self.alpha = max(0.0, min(1.0, float(alpha)))
        self._win: deque[float] = deque(maxlen=max(1, int(median_window)))
        self._ema: float | None = None

    def push(self, value: float | None) -> float | None:
        if value is None:
            return self._ema            # no fabrication: return last real-derived value (or None)
        v = float(value)
        self._win.append(v)
        med = median(self._win)
        self._ema = med if self._ema is None else self.alpha * v + (1.0 - self.alpha) * self._ema
        return round(self._ema, 10)

    @property
    def value(self) -> float | None:
        return self._ema


__all__ = ["EmaMedianSmoother"]
