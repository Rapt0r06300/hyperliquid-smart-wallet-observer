"""V15 #199 — Detect Hyperliquid TWAP orders (regular, similar-size child fills = informed flow)."""

from __future__ import annotations

from dataclasses import dataclass
from statistics import fmean, pstdev
from typing import Sequence


@dataclass(frozen=True, slots=True)
class TwapDetection:
    is_twap: bool
    child_count: int
    interval_regularity: float    # 0..1 (1 = perfectly regular spacing)
    size_uniformity: float        # 0..1 (1 = identical sizes)
    total_notional_usd: float
    side: str | None


def detect_twap(
    fills: Sequence[tuple[int, float, str]],   # (ts_ms, notional_usd, side)
    *,
    min_children: int = 4,
    max_interval_cv: float = 0.35,
    max_size_cv: float = 0.35,
) -> TwapDetection:
    """A TWAP = many child orders, evenly spaced, similar size, same side."""
    fs = sorted(fills, key=lambda f: int(f[0]))
    n = len(fs)
    sides = {str(f[2]).upper() for f in fs}
    side = next(iter(sides)) if len(sides) == 1 else None
    total = round(sum(float(f[1]) for f in fs), 6)
    if n < min_children or side is None:
        return TwapDetection(False, n, 0.0, 0.0, total, side)
    intervals = [int(fs[i][0]) - int(fs[i - 1][0]) for i in range(1, n)]
    sizes = [float(f[1]) for f in fs]
    def _cv(xs):
        m = fmean(xs)
        return (pstdev(xs) / m) if m > 0 else 1.0
    int_cv = _cv(intervals) if intervals else 1.0
    size_cv = _cv(sizes)
    interval_reg = max(0.0, 1.0 - int_cv)
    size_uni = max(0.0, 1.0 - size_cv)
    is_twap = int_cv <= max_interval_cv and size_cv <= max_size_cv
    return TwapDetection(is_twap, n, round(interval_reg, 6), round(size_uni, 6), total, side)


__all__ = ["TwapDetection", "detect_twap"]
