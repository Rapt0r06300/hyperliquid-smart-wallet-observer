"""V15 #192 — RSI + overheat penalty (don't chase overbought/oversold)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence


def rsi(closes: Sequence[float], period: int = 14) -> float | None:
    c = [float(x) for x in closes]
    if len(c) < period + 1:
        return None
    gains = 0.0
    losses = 0.0
    for i in range(1, period + 1):
        ch = c[i] - c[i - 1]
        if ch >= 0:
            gains += ch
        else:
            losses -= ch
    avg_gain = gains / period
    avg_loss = losses / period
    for i in range(period + 1, len(c)):
        ch = c[i] - c[i - 1]
        gain = max(0.0, ch)
        loss = max(0.0, -ch)
        avg_gain = (avg_gain * (period - 1) + gain) / period
        avg_loss = (avg_loss * (period - 1) + loss) / period
    if avg_loss <= 1e-12:
        return 100.0
    rs = avg_gain / avg_loss
    return round(100.0 - (100.0 / (1.0 + rs)), 4)


@dataclass(frozen=True, slots=True)
class RsiOverheat:
    rsi: float | None
    overheated: bool
    penalty_bps: float


def rsi_overheat_penalty(
    rsi_value: float | None,
    side: str,
    *,
    overbought: float = 70.0,
    oversold: float = 30.0,
    penalty_bps: float = 15.0,
) -> RsiOverheat:
    """Penalise chasing: long into overbought, or short into oversold."""
    if rsi_value is None:
        return RsiOverheat(None, False, 0.0)
    s = str(side or "").upper()
    overheated = (s in {"LONG", "BUY"} and rsi_value >= overbought) or (s in {"SHORT", "SELL"} and rsi_value <= oversold)
    return RsiOverheat(rsi_value, overheated, penalty_bps if overheated else 0.0)


__all__ = ["rsi", "RsiOverheat", "rsi_overheat_penalty"]
