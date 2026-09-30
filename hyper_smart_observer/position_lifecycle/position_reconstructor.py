from __future__ import annotations

from datetime import datetime

from hyper_smart_observer.position_lifecycle.action_classifier import classify_position_action
from hyper_smart_observer.position_lifecycle.lifecycle_models import PositionAction


def action_from_fill_row(row) -> PositionAction:
    action_type = classify_position_action(row["side"], start_position=_float(row["start_position"]))
    warnings = [] if action_type.value != "UNKNOWN" else ["ambiguous fill action"]
    return PositionAction(
        wallet_address=row["wallet_address"],
        coin=row["coin"],
        action_type=action_type,
        timestamp=datetime.fromisoformat(row["timestamp"]),
        size=_float(row["size"]),
        price=_float(row["price"]),
        closed_pnl=_float(row["closed_pnl"]),
        fee=_float(row["fee"]),
        confidence=0.9 if not warnings else 0.2,
        warnings=warnings,
    )


def _float(value) -> float | None:
    try:
        return None if value in (None, "") else float(value)
    except (TypeError, ValueError):
        return None
