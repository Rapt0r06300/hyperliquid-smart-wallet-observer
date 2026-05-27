from __future__ import annotations

from hyper_smart_observer.hyperliquid_client.models import PositionActionType


def classify_position_action(direction: str | None, *, start_position: float | None = None) -> PositionActionType:
    text = (direction or "").strip().lower()
    if "open" in text and "long" in text:
        return PositionActionType.OPEN_LONG
    if "open" in text and "short" in text:
        return PositionActionType.OPEN_SHORT
    if "close" in text and "long" in text:
        return PositionActionType.CLOSE_LONG
    if "close" in text and "short" in text:
        return PositionActionType.CLOSE_SHORT
    if "reduce" in text and "long" in text:
        return PositionActionType.REDUCE_LONG
    if "reduce" in text and "short" in text:
        return PositionActionType.REDUCE_SHORT
    if "increase" in text and "long" in text:
        return PositionActionType.INCREASE_LONG
    if "increase" in text and "short" in text:
        return PositionActionType.INCREASE_SHORT
    if start_position == 0 and "long" in text:
        return PositionActionType.OPEN_LONG
    if start_position == 0 and "short" in text:
        return PositionActionType.OPEN_SHORT
    return PositionActionType.UNKNOWN
