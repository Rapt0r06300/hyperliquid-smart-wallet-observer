from __future__ import annotations

try:
    from enum import StrEnum
except ImportError:
    from enum import Enum
    class StrEnum(str, Enum): pass


class ClosingType(StrEnum):
    TAKE_PROFIT_FULL = "TAKE_PROFIT_FULL"
    TAKE_PROFIT_PARTIAL = "TAKE_PROFIT_PARTIAL"
    STOP_LOSS = "STOP_LOSS"
    TRAILING_EXIT = "TRAILING_EXIT"
    REDUCE_RISK = "REDUCE_RISK"
    FLIP_EXIT = "FLIP_EXIT"
    TIME_BASED_EXIT = "TIME_BASED_EXIT"
    PANIC_EXIT = "PANIC_EXIT"
    FUNDING_EXIT = "FUNDING_EXIT"
    LIQUIDITY_EXIT = "LIQUIDITY_EXIT"
    UNKNOWN_EXIT = "UNKNOWN_EXIT"


def classify_closing(*, action: str, closed_pnl: float | None = None) -> ClosingType:
    action_norm = action.upper()
    if action_norm == "FLIP":
        return ClosingType.FLIP_EXIT
    if action_norm == "REDUCE":
        if closed_pnl is not None and closed_pnl > 0:
            return ClosingType.TAKE_PROFIT_PARTIAL
        return ClosingType.REDUCE_RISK
    if action_norm == "CLOSE":
        if closed_pnl is not None and closed_pnl > 0:
            return ClosingType.TAKE_PROFIT_FULL
        if closed_pnl is not None and closed_pnl < 0:
            return ClosingType.STOP_LOSS
    return ClosingType.UNKNOWN_EXIT
