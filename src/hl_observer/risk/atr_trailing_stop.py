"""V15 #200 — ATR trailing stop (volatility-adapted exit) for paper simulation."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence


def atr(highs: Sequence[float], lows: Sequence[float], closes: Sequence[float], period: int = 14) -> float | None:
    n = min(len(highs), len(lows), len(closes))
    if n < period + 1:
        return None
    trs: list[float] = []
    for i in range(1, n):
        h, l, pc = float(highs[i]), float(lows[i]), float(closes[i - 1])
        trs.append(max(h - l, abs(h - pc), abs(l - pc)))
    if len(trs) < period:
        return None
    a = sum(trs[:period]) / period
    for tr in trs[period:]:
        a = (a * (period - 1) + tr) / period
    return round(a, 8)


@dataclass(frozen=True, slots=True)
class TrailingStop:
    stop_price: float
    should_exit: bool


def trailing_stop(
    *,
    side: str,
    atr_value: float,
    extreme_price: float,     # highest price since entry (long) / lowest (short)
    current_price: float,
    multiplier: float = 3.0,
) -> TrailingStop:
    s = str(side or "").upper()
    dist = float(atr_value) * float(multiplier)
    if s in {"LONG", "BUY"}:
        stop = float(extreme_price) - dist
        return TrailingStop(round(stop, 8), float(current_price) <= stop)
    stop = float(extreme_price) + dist
    return TrailingStop(round(stop, 8), float(current_price) >= stop)


__all__ = ["atr", "TrailingStop", "trailing_stop"]
