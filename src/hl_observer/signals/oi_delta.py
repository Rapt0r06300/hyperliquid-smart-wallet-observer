"""V15 #195 — Open-interest delta signal (rising OI + price move = real positioning)."""

from __future__ import annotations

from dataclasses import dataclass


def _clamp(x: float, lo: float = 0.0, hi: float = 1.0) -> float:
    return max(lo, min(hi, x))


@dataclass(frozen=True, slots=True)
class OiDeltaSignal:
    oi_change_pct: float
    price_change_bps: float
    signal: str            # NEW_LONGS | NEW_SHORTS | LONG_UNWIND | SHORT_UNWIND | NEUTRAL
    side: str | None       # LONG | SHORT | None
    strength: float        # 0..1


def oi_delta_signal(
    *,
    oi_prev: float,
    oi_now: float,
    price_prev: float,
    price_now: float,
    min_oi_change_pct: float = 0.5,
    min_price_bps: float = 5.0,
) -> OiDeltaSignal:
    oi_chg = ((float(oi_now) - float(oi_prev)) / float(oi_prev) * 100.0) if oi_prev else 0.0
    px_bps = ((float(price_now) - float(price_prev)) / float(price_prev) * 10_000.0) if price_prev else 0.0
    rising = oi_chg >= min_oi_change_pct
    falling = oi_chg <= -min_oi_change_pct
    up = px_bps >= min_price_bps
    down = px_bps <= -min_price_bps
    signal = "NEUTRAL"; side = None
    if rising and up:
        signal, side = "NEW_LONGS", "LONG"
    elif rising and down:
        signal, side = "NEW_SHORTS", "SHORT"
    elif falling and up:
        signal, side = "SHORT_UNWIND", "LONG"
    elif falling and down:
        signal, side = "LONG_UNWIND", "SHORT"
    strength = _clamp((abs(oi_chg) / 5.0) * 0.5 + (abs(px_bps) / 50.0) * 0.5)
    return OiDeltaSignal(round(oi_chg, 4), round(px_bps, 4), signal, side, round(strength, 6))


__all__ = ["OiDeltaSignal", "oi_delta_signal"]
