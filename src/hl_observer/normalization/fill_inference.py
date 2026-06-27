from __future__ import annotations

from dataclasses import dataclass

from hl_observer.models import Fill, PositionAction, SourceMeta
from hl_observer.normalization.normalize import classify_position_delta


@dataclass(frozen=True, slots=True)
class InferredFill:
    allowed_for_paper: bool
    action: PositionAction
    confidence: float
    size_delta: float
    reason: str
    fill: Fill | None = None


def infer_fill_from_position_delta(
    *,
    wallet: str,
    coin: str,
    previous_size: float,
    current_size: float,
    mark_price: float,
    observed_at_ms: int,
    meta: SourceMeta,
) -> InferredFill:
    action = classify_position_delta(previous_size, current_size)
    if action == PositionAction.UNKNOWN:
        return InferredFill(False, action, 0.0, 0.0, "UNKNOWN_DELTA_NO_INFERRED_FILL")
    size_delta = abs(float(current_size) - float(previous_size))
    if size_delta <= 0 or mark_price <= 0:
        return InferredFill(False, PositionAction.UNKNOWN, 0.0, size_delta, "INVALID_INFERENCE_INPUT")
    fill = Fill(
        wallet=wallet,
        coin=coin,
        direction=_direction_for_action(action),
        side="B" if action in {PositionAction.OPEN_LONG, PositionAction.ADD, PositionAction.INCREASE} and current_size > previous_size else "S",
        size=size_delta,
        price=mark_price,
        time_ms=observed_at_ms,
        start_position=previous_size,
        meta=meta,
    )
    return InferredFill(
        allowed_for_paper=action != PositionAction.UNKNOWN and not meta.is_stale,
        action=action,
        confidence=0.35 if not meta.is_stale else 0.0,
        size_delta=size_delta,
        reason="INFERRED_FROM_POSITION_POLLING_LOW_CONFIDENCE",
        fill=fill,
    )


def _direction_for_action(action: PositionAction) -> str:
    if action == PositionAction.OPEN_LONG:
        return "Open Long"
    if action == PositionAction.OPEN_SHORT:
        return "Open Short"
    if action == PositionAction.CLOSE_LONG:
        return "Close Long"
    if action == PositionAction.CLOSE_SHORT:
        return "Close Short"
    if action in {PositionAction.ADD, PositionAction.INCREASE}:
        return "Open"
    if action == PositionAction.REDUCE:
        return "Close"
    return "Unknown"
