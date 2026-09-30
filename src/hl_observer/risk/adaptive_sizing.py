"""Conservative finite adaptive paper sizing."""

from __future__ import annotations

from dataclasses import dataclass
import math

BASE_PCT = 2.0
CAP_PCT = 5.0
FLOOR_PCT = 0.5
LOSS_FACTOR = 0.8
WIN_FACTOR = 1.1


@dataclass(frozen=True, slots=True)
class SizingDecision:
    size_pct: float
    multiplier: float
    confidence: float
    capped: bool
    floored: bool


def compute_size_pct(
    *,
    consecutive_losses: int = 0,
    consecutive_wins: int = 0,
    base_pct: float = BASE_PCT,
    cap_pct: float = CAP_PCT,
    floor_pct: float = FLOOR_PCT,
    confidence: float = 1.0,
) -> SizingDecision:
    if (
        not isinstance(consecutive_losses, int) or isinstance(consecutive_losses, bool)
        or not isinstance(consecutive_wins, int) or isinstance(consecutive_wins, bool)
        or consecutive_losses < 0 or consecutive_wins < 0
    ):
        raise ValueError("streak counters must be non-negative integers")
    try:
        base, cap, floor, conf = map(float, (base_pct, cap_pct, floor_pct, confidence))
    except (TypeError, ValueError, OverflowError) as exc:
        raise ValueError("sizing inputs must be numeric") from exc
    if any(not math.isfinite(value) for value in (base, cap, floor, conf)):
        raise ValueError("sizing inputs must be finite")
    if base < 0.0 or floor < 0.0 or cap < floor or not 0.0 <= conf <= 1.0:
        raise ValueError("invalid sizing bounds")
    multiplier = (LOSS_FACTOR ** consecutive_losses) * (WIN_FACTOR ** consecutive_wins)
    raw = base * multiplier * conf
    if not math.isfinite(raw):
        raise ValueError("sizing result is non-finite")
    if conf <= 0.0:
        return SizingDecision(0.0, multiplier, conf, False, False)
    capped = raw > cap
    floored = raw < floor
    size = min(cap, max(floor, raw))
    return SizingDecision(size, multiplier, conf, capped, floored)


def size_to_notional(size_pct: float, equity_usdc: float) -> float:
    try:
        size, equity = float(size_pct), float(equity_usdc)
    except (TypeError, ValueError, OverflowError) as exc:
        raise ValueError("size and equity must be numeric") from exc
    if not math.isfinite(size) or not math.isfinite(equity) or size < 0.0 or equity < 0.0:
        raise ValueError("size and equity must be finite and non-negative")
    return size / 100.0 * equity
