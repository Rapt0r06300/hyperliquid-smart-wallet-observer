"""Detect spreads that should block fresh paper entries."""

from __future__ import annotations

from dataclasses import dataclass
import math


@dataclass(frozen=True, slots=True)
class SpreadRiskDecision:
    ok: bool
    spread_bps: float
    reason: str | None


def detect_abnormal_spread(*, bid: float, ask: float, max_spread_bps: float = 12.0) -> SpreadRiskDecision:
    try:
        bid_f, ask_f, maximum = float(bid), float(ask), float(max_spread_bps)
    except (TypeError, ValueError):
        return SpreadRiskDecision(False, 0.0, "SPREAD_INPUT_INVALID")
    if (
        not all(math.isfinite(value) for value in (bid_f, ask_f, maximum))
        or bid_f <= 0.0
        or ask_f <= 0.0
        or ask_f < bid_f
        or maximum < 0.0
    ):
        return SpreadRiskDecision(False, 0.0, "SPREAD_INPUT_INVALID")
    mid = (bid_f + ask_f) / 2.0
    spread = (ask_f - bid_f) / mid * 10_000.0
    if not math.isfinite(spread):
        return SpreadRiskDecision(False, 0.0, "SPREAD_INPUT_INVALID")
    if spread > maximum:
        return SpreadRiskDecision(False, round(spread, 8), "ABNORMAL_SPREAD")
    return SpreadRiskDecision(True, round(spread, 8), None)


__all__ = ["SpreadRiskDecision", "detect_abnormal_spread"]
