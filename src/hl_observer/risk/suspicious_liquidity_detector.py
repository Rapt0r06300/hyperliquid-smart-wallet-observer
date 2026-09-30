"""Liquidity cliff detector for paper entries."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class LiquidityRiskDecision:
    ok: bool
    top_depth_usdt: float
    next_depth_usdt: float
    cliff_ratio: float
    reason: str | None


def detect_liquidity_cliff(
    *,
    top_depth_usdt: float,
    next_depth_usdt: float,
    min_top_depth_usdt: float = 500.0,
    max_cliff_ratio: float = 4.0,
) -> LiquidityRiskDecision:
    top = max(0.0, float(top_depth_usdt or 0.0))
    nxt = max(0.0, float(next_depth_usdt or 0.0))
    if top < float(min_top_depth_usdt):
        return LiquidityRiskDecision(False, top, nxt, 0.0, "TOP_DEPTH_TOO_LOW")
    ratio = top / max(1e-9, nxt)
    if ratio > float(max_cliff_ratio):
        return LiquidityRiskDecision(False, top, nxt, round(ratio, 8), "LIQUIDITY_CLIFF")
    return LiquidityRiskDecision(True, top, nxt, round(ratio, 8), None)


__all__ = ["LiquidityRiskDecision", "detect_liquidity_cliff"]
