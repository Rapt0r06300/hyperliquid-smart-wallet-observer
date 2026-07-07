"""Multi-timeframe direction feature (S4 — V9, Harrier / mlmodelpoly A3).

Computes a simple, deterministic trend direction (UP / DOWN / FLAT) per timeframe
from real close prices, plus a combined multi-TF read (e.g. 5m + 15m). Used to
confirm that a copied entry is aligned with the prevailing trend rather than
fighting it. Pure: missing/short data -> FLAT (never fabricated). SAFETY: read-only.
"""

from __future__ import annotations

from dataclasses import dataclass

UP = "UP"
DOWN = "DOWN"
FLAT = "FLAT"


@dataclass(frozen=True, slots=True)
class DirectionConfig:
    fast_period: int = 9
    slow_period: int = 21
    flat_threshold_bps: float = 5.0   # |fast-slow|/slow below this -> FLAT


@dataclass(frozen=True, slots=True)
class MultiTFDirection:
    tf_fast: str
    tf_slow: str
    agree: bool
    combined: str          # UP/DOWN/FLAT
    strength_bps: float    # signed: + = up bias, - = down bias (from the slower TF)


def _ema(values: list[float], period: int) -> float | None:
    if period <= 0 or len(values) < period:
        return None
    k = 2.0 / (period + 1.0)
    ema = values[0]
    for v in values[1:]:
        ema = v * k + ema * (1.0 - k)
    return ema


def timeframe_direction(closes: list[float], config: DirectionConfig | None = None) -> str:
    """Direction of one timeframe from its close series."""
    cfg = config or DirectionConfig()
    closes = [float(c) for c in (closes or []) if c is not None]
    fast = _ema(closes, cfg.fast_period)
    slow = _ema(closes, cfg.slow_period)
    if fast is None or slow is None or slow == 0:
        return FLAT
    delta_bps = (fast - slow) / abs(slow) * 10_000.0
    if delta_bps > cfg.flat_threshold_bps:
        return UP
    if delta_bps < -cfg.flat_threshold_bps:
        return DOWN
    return FLAT


def _signed_strength_bps(closes: list[float], config: DirectionConfig) -> float:
    closes = [float(c) for c in (closes or []) if c is not None]
    fast = _ema(closes, config.fast_period)
    slow = _ema(closes, config.slow_period)
    if fast is None or slow is None or slow == 0:
        return 0.0
    return (fast - slow) / abs(slow) * 10_000.0


def multi_tf_direction(
    closes_fast_tf: list[float],
    closes_slow_tf: list[float],
    config: DirectionConfig | None = None,
) -> MultiTFDirection:
    """Combine two timeframes (e.g. 5m as fast TF, 15m as slow TF)."""
    cfg = config or DirectionConfig()
    d_fast = timeframe_direction(closes_fast_tf, cfg)
    d_slow = timeframe_direction(closes_slow_tf, cfg)
    agree = d_fast == d_slow and d_fast != FLAT
    if agree:
        combined = d_fast
    elif FLAT in (d_fast, d_slow):
        # one TF flat -> follow the non-flat one but it's a weak read
        combined = d_fast if d_slow == FLAT else d_slow
    else:
        combined = FLAT  # outright conflict -> no directional edge
    return MultiTFDirection(
        tf_fast=d_fast,
        tf_slow=d_slow,
        agree=agree,
        combined=combined,
        strength_bps=round(_signed_strength_bps(closes_slow_tf, cfg), 6),
    )


def aligns_with(direction_side: str, combined: str) -> bool:
    """True if a LONG/SHORT entry agrees with the combined direction (FLAT -> True/neutral)."""
    side = direction_side.upper()
    if combined == FLAT:
        return True
    if side in {"LONG", "BUY"}:
        return combined == UP
    if side in {"SHORT", "SELL"}:
        return combined == DOWN
    return True


__all__ = [
    "UP",
    "DOWN",
    "FLAT",
    "DirectionConfig",
    "MultiTFDirection",
    "timeframe_direction",
    "multi_tf_direction",
    "aligns_with",
]
