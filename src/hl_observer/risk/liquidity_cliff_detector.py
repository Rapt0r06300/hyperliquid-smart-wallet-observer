"""Detect shallow depth cliffs around the simulated entry price."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable


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


__all__ = ["LiquidityCliffResult", "detect_liquidity_cliff"]
