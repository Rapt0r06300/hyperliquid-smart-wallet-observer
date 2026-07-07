"""Detect spreads that should block fresh paper entries."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class SpreadRiskDecision:
    ok: bool
    spread_bps: float
    reason: str | None


def detect_abnormal_spread(*, bid: float, ask: float, max_spread_bps: float = 12.0) -> SpreadRiskDecision:
    bid_f = float(bid or 0.0)
    ask_f = float(ask or 0.0)
    if bid_f <= 0 or ask_f <= 0 or ask_f < bid_f:
        return SpreadRiskDecision(False, 0.0, "SPREAD_INPUT_INVALID")
    mid = (bid_f + ask_f) / 2.0
    spread = (ask_f - bid_f) / mid * 10_000.0
    if spread > float(max_spread_bps):
        return SpreadRiskDecision(False, round(spread, 8), "ABNORMAL_SPREAD")
    return SpreadRiskDecision(True, round(spread, 8), None)


__all__ = ["SpreadRiskDecision", "detect_abnormal_spread"]
