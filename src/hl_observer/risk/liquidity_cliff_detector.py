"""Detect shallow depth cliffs around the simulated entry price."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable
import math


@dataclass(frozen=True, slots=True)
class LiquidityCliffResult:
    blocked: bool
    reason: str
    near_depth_usdt: float
    far_depth_usdt: float
    cliff_ratio: float


def detect_liquidity_cliff(levels: Iterable[dict[str, float]], *, min_near_depth_usdt: float = 5_000.0, max_cliff_ratio: float = 4.0) -> LiquidityCliffResult:
    rows = list(levels)
    near = sum(float(row.get("notional_usdt", 0.0)) for row in rows[:3])
    far = sum(float(row.get("notional_usdt", 0.0)) for row in rows[3:10])
    ratio = far / max(near, 1e-9)
    blocked = near < min_near_depth_usdt or ratio > max_cliff_ratio
    reason = "LIQUIDITY_CLIFF" if blocked else "OK"
    return LiquidityCliffResult(blocked=blocked, reason=reason, near_depth_usdt=round(near, 8), far_depth_usdt=round(far, 8), cliff_ratio=round(ratio, 8))


def liquidity_cliff_receipt(levels: Iterable[dict[str, float]], *, min_near_depth_usdt: float = 5_000.0, max_cliff_ratio: float = 4.0) -> dict[str, object]:
    """Expose a finite-only liquidity cliff diagnostic."""

    rows = list(levels)
    try:
        valid = bool(rows) and all(isinstance(row, dict) and math.isfinite(float(row.get("notional_usdt", float("nan")))) and float(row.get("notional_usdt", -1.0)) >= 0.0 for row in rows)
    except (TypeError, ValueError, OverflowError):
        valid = False
    if not valid:
        return {"status": "UNMEASURABLE", "reason": "LEVELS_INVALID"}
    result = detect_liquidity_cliff(rows, min_near_depth_usdt=min_near_depth_usdt, max_cliff_ratio=max_cliff_ratio)
    return {"status": "PROVEN", "blocked": result.blocked, "reason": result.reason, "near_depth_usdt": result.near_depth_usdt, "far_depth_usdt": result.far_depth_usdt, "cliff_ratio": result.cliff_ratio}


__all__ = ["LiquidityCliffResult", "detect_liquidity_cliff", "liquidity_cliff_receipt"]
