from __future__ import annotations

from enum import StrEnum


class OpeningType(StrEnum):
    BREAKOUT_LONG = "BREAKOUT_LONG"
    BREAKOUT_SHORT = "BREAKOUT_SHORT"
    PULLBACK_LONG = "PULLBACK_LONG"
    PULLBACK_SHORT = "PULLBACK_SHORT"
    REVERSAL_LONG = "REVERSAL_LONG"
    REVERSAL_SHORT = "REVERSAL_SHORT"
    MOMENTUM_CHASE_LONG = "MOMENTUM_CHASE_LONG"
    MOMENTUM_CHASE_SHORT = "MOMENTUM_CHASE_SHORT"
    MEAN_REVERSION_LONG = "MEAN_REVERSION_LONG"
    MEAN_REVERSION_SHORT = "MEAN_REVERSION_SHORT"
    LIQUIDITY_SWEEP_LONG = "LIQUIDITY_SWEEP_LONG"
    LIQUIDITY_SWEEP_SHORT = "LIQUIDITY_SWEEP_SHORT"
    FUNDING_CARRY_LONG = "FUNDING_CARRY_LONG"
    FUNDING_CARRY_SHORT = "FUNDING_CARRY_SHORT"
    CLUSTER_FOLLOW_LONG = "CLUSTER_FOLLOW_LONG"
    CLUSTER_FOLLOW_SHORT = "CLUSTER_FOLLOW_SHORT"
    DCA_LONG = "DCA_LONG"
    DCA_SHORT = "DCA_SHORT"
    SCALE_IN_LONG = "SCALE_IN_LONG"
    SCALE_IN_SHORT = "SCALE_IN_SHORT"
    HEDGE_OR_UNKNOWN = "HEDGE_OR_UNKNOWN"
    UNKNOWN = "UNKNOWN"


def classify_opening(*, action: str, side: str | None, direction: str | None = None) -> OpeningType:
    side_norm = (side or "").upper()
    direction_norm = (direction or "").lower()
    if action.upper() == "ADD":
        if side_norm == "LONG":
            return OpeningType.SCALE_IN_LONG
        if side_norm == "SHORT":
            return OpeningType.SCALE_IN_SHORT
    if "dca" in direction_norm or "average" in direction_norm:
        return OpeningType.DCA_LONG if side_norm == "LONG" else OpeningType.DCA_SHORT if side_norm == "SHORT" else OpeningType.UNKNOWN
    if action.upper() in {"OPEN", "FLIP"}:
        if side_norm == "LONG":
            return OpeningType.MOMENTUM_CHASE_LONG
        if side_norm == "SHORT":
            return OpeningType.MOMENTUM_CHASE_SHORT
    return OpeningType.UNKNOWN
