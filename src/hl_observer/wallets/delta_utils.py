from __future__ import annotations
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from hl_observer.storage.models import PositionDeltaModel

def copy_delta_action(row: PositionDeltaModel) -> str:
    raw = f"{row.delta_type or ''} {row.action or ''} {row.previous_side or ''} {row.new_side or ''} {row.side or ''}".lower()
    previous = (row.previous_side or "").lower()
    new = (row.new_side or row.side or "").lower()
    if "open" in raw:
        if "short" in raw or new == "short" or row.current_size < 0:
            return "OPEN_SHORT"
        if "long" in raw or new == "long" or row.current_size > 0:
            return "OPEN_LONG"
    if "add" in raw:
        return "ADD"
    if "increase" in raw:
        return "INCREASE"
    if "reduce" in raw:
        return "REDUCE"
    if "close" in raw:
        if "short" in raw or previous == "short" or row.previous_size < 0:
            return "CLOSE_SHORT"
        if "long" in raw or previous == "long" or row.previous_size > 0:
            return "CLOSE_LONG"
    return "UNKNOWN"

def copy_delta_direction(row: PositionDeltaModel, action: str | None = None) -> str | None:
    action = action or copy_delta_action(row)
    if action == "OPEN_LONG":
        return "LONG"
    if action == "OPEN_SHORT":
        return "SHORT"
    if action in {"ADD", "INCREASE"}:
        if row.current_size > 0 or (row.new_side or row.side or "").lower() == "long":
            return "LONG"
        if row.current_size < 0 or (row.new_side or row.side or "").lower() == "short":
            return "SHORT"
    if action in {"REDUCE", "CLOSE_LONG", "CLOSE_SHORT"}:
        if action == "CLOSE_LONG":
            return "LONG"
        if action == "CLOSE_SHORT":
            return "SHORT"
        if row.previous_size > 0 or (row.previous_side or "").lower() == "long":
            return "LONG"
        if row.previous_size < 0 or (row.previous_side or "").lower() == "short":
            return "SHORT"
    return None

def delta_event_time_ms(row: PositionDeltaModel) -> int:
    """Prefer exchange time so historical backfills do not count as live bot actions."""
    return int(row.exchange_ts or row.detected_at_ms or 0)
