from __future__ import annotations

from dataclasses import dataclass, field

from hl_observer.models import DataQuality, NormalizedDelta, PositionAction, SourceMeta


@dataclass(frozen=True, slots=True)
class NormalizationDecision:
    allowed_for_paper: bool
    action: PositionAction
    reason: str
    warnings: tuple[str, ...] = field(default_factory=tuple)


def classify_position_delta(previous_size: float, current_size: float, *, epsilon: float = 1e-12) -> PositionAction:
    prev = _zero_small(previous_size, epsilon)
    cur = _zero_small(current_size, epsilon)
    if prev == 0 and cur > 0:
        return PositionAction.OPEN_LONG
    if prev == 0 and cur < 0:
        return PositionAction.OPEN_SHORT
    if prev > 0 and cur > 0:
        return PositionAction.INCREASE if cur > prev else PositionAction.REDUCE if cur < prev else PositionAction.UNKNOWN
    if prev < 0 and cur < 0:
        return PositionAction.INCREASE if abs(cur) > abs(prev) else PositionAction.REDUCE if abs(cur) < abs(prev) else PositionAction.UNKNOWN
    if prev > 0 and cur == 0:
        return PositionAction.CLOSE_LONG
    if prev < 0 and cur == 0:
        return PositionAction.CLOSE_SHORT
    if (prev > 0 and cur < 0) or (prev < 0 and cur > 0):
        return PositionAction.UNKNOWN
    return PositionAction.UNKNOWN


def normalize_position_delta(
    *,
    wallet: str,
    coin: str,
    previous_size: float,
    current_size: float,
    meta: SourceMeta,
) -> NormalizedDelta:
    action = classify_position_delta(previous_size, current_size)
    warnings: list[str] = []
    confidence = 0.95
    if action == PositionAction.UNKNOWN:
        warnings.append("UNKNOWN_DELTA_NO_PAPER_INTENT")
        confidence = 0.0
    if meta.data_quality in {DataQuality.BAD, DataQuality.UNKNOWN} or meta.is_stale:
        warnings.append("LOW_SOURCE_QUALITY_NO_PAPER_INTENT")
        confidence = min(confidence, 0.25)
    return NormalizedDelta(
        wallet=wallet,
        coin=coin,
        previous_size=previous_size,
        current_size=current_size,
        action=action,
        confidence=confidence,
        warnings=warnings,
        meta=meta,
    )


def classify_fill_action(
    *,
    direction: str | None,
    start_position: float | None,
    resulting_position: float | None = None,
) -> NormalizationDecision:
    normalized_dir = str(direction or "").strip().lower()
    if not normalized_dir or start_position is None:
        return NormalizationDecision(False, PositionAction.UNKNOWN, "FILL_DATA_INSUFFICIENT")
    start = _zero_small(float(start_position))
    if normalized_dir == "open long":
        action = PositionAction.OPEN_LONG if start == 0 else PositionAction.ADD
        return NormalizationDecision(True, action, "FILL_OPEN_LONG")
    if normalized_dir == "open short":
        action = PositionAction.OPEN_SHORT if start == 0 else PositionAction.ADD
        return NormalizationDecision(True, action, "FILL_OPEN_SHORT")
    if normalized_dir == "close long":
        if resulting_position is None:
            return NormalizationDecision(False, PositionAction.UNKNOWN, "CLOSE_RESULT_UNKNOWN")
        result = _zero_small(float(resulting_position))
        action = PositionAction.CLOSE_LONG if result == 0 else PositionAction.REDUCE
        return NormalizationDecision(action != PositionAction.UNKNOWN, action, "FILL_CLOSE_LONG")
    if normalized_dir == "close short":
        if resulting_position is None:
            return NormalizationDecision(False, PositionAction.UNKNOWN, "CLOSE_RESULT_UNKNOWN")
        result = _zero_small(float(resulting_position))
        action = PositionAction.CLOSE_SHORT if result == 0 else PositionAction.REDUCE
        return NormalizationDecision(action != PositionAction.UNKNOWN, action, "FILL_CLOSE_SHORT")
    return NormalizationDecision(False, PositionAction.UNKNOWN, "FILL_DIRECTION_UNKNOWN")


def _zero_small(value: float, epsilon: float = 1e-12) -> float:
    value = float(value)
    return 0.0 if abs(value) <= epsilon else value
