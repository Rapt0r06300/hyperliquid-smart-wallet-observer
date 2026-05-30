from __future__ import annotations

from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field


class PositionSide(StrEnum):
    LONG = "LONG"
    SHORT = "SHORT"
    FLAT = "FLAT"
    UNKNOWN = "UNKNOWN"


class PositionAction(StrEnum):
    OPEN = "OPEN"
    ADD = "ADD"
    REDUCE = "REDUCE"
    CLOSE = "CLOSE"
    FLIP = "FLIP"
    UNKNOWN = "UNKNOWN"


class ConfidenceLevel(StrEnum):
    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    UNKNOWN = "UNKNOWN"


class PositionDeltaRecord(BaseModel):
    wallet_address: str
    coin: str
    previous_side: PositionSide
    new_side: PositionSide
    previous_size: float
    new_size: float
    delta_size: float
    delta_notional_usdc: float | None = None
    action: PositionAction
    sub_actions: list[dict[str, Any]] = Field(default_factory=list)
    intent: str = "UNKNOWN"  # AGGRESSIVE, PASSIVE, UNKNOWN
    trade_narrative: str | None = None
    reconciliation_metadata: dict[str, Any] = Field(default_factory=dict)
    exchange_ts: int | None = None
    fill_id: int | None = None
    source_event_id: int | None = None
    side: str | None = None
    price: float | None = None
    fill_size: float | None = None
    confidence_score: float = 0.0
    confidence_level: ConfidenceLevel = ConfidenceLevel.UNKNOWN
    warnings: list[str] = Field(default_factory=list)
    reason: str | None = None
    source_evidence: dict[str, Any] = Field(default_factory=dict)
    source: str = "user_fills"
    notes: list[str] = Field(default_factory=list)
    raw: dict[str, Any] = Field(default_factory=dict)


def safe_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def first_present(payload: dict[str, Any], *keys: str) -> Any:
    for key in keys:
        if key in payload and payload[key] is not None:
            return payload[key]
    return None


def position_side(size: float | None) -> PositionSide:
    if size is None:
        return PositionSide.UNKNOWN
    if size > 0:
        return PositionSide.LONG
    if size < 0:
        return PositionSide.SHORT
    return PositionSide.FLAT


def fill_timestamp(fill: dict[str, Any]) -> int:
    return int(first_present(fill, "time", "timestamp") or 0)


def fill_coin(fill: dict[str, Any]) -> str:
    return str(first_present(fill, "coin", "coinName") or "UNKNOWN").upper()


def fill_price(fill: dict[str, Any]) -> float | None:
    return safe_float(first_present(fill, "px", "price"))


def fill_size(fill: dict[str, Any]) -> float | None:
    return safe_float(first_present(fill, "sz", "size"))


def start_position(fill: dict[str, Any]) -> float | None:
    return safe_float(first_present(fill, "startPosition", "start_position"))


def signed_fill_size(fill: dict[str, Any]) -> float | None:
    size = fill_size(fill)
    if size is None:
        return None

    side = str(first_present(fill, "side") or "").strip().lower()
    if side in {"b", "buy", "bid"}:
        return abs(size)
    if side in {"a", "s", "sell", "ask"}:
        return -abs(size)

    direction = str(first_present(fill, "dir", "direction") or "").strip().lower()
    if "open long" in direction or "close short" in direction:
        return abs(size)
    if "open short" in direction or "close long" in direction:
        return -abs(size)
    return None


def classify_action(previous_size: float, new_size: float, *, direction_unclear: bool = False) -> PositionAction:
    if direction_unclear:
        return PositionAction.UNKNOWN
    previous_side = position_side(previous_size)
    new_side = position_side(new_size)
    if previous_side == PositionSide.FLAT and new_side in {PositionSide.LONG, PositionSide.SHORT}:
        return PositionAction.OPEN
    if previous_side in {PositionSide.LONG, PositionSide.SHORT} and new_side == PositionSide.FLAT:
        return PositionAction.CLOSE
    if previous_side in {PositionSide.LONG, PositionSide.SHORT} and new_side in {
        PositionSide.LONG,
        PositionSide.SHORT,
    }:
        if previous_side != new_side:
            return PositionAction.FLIP
        if abs(new_size) > abs(previous_size):
            return PositionAction.ADD
        if abs(new_size) < abs(previous_size):
            return PositionAction.REDUCE
    return PositionAction.UNKNOWN


def confidence_for_fill(fill: dict[str, Any], *, direction_unclear: bool, has_start_position: bool) -> tuple[float, list[str]]:
    notes: list[str] = []
    if direction_unclear:
        notes.append("direction_unclear")
    if fill_size(fill) is None:
        notes.append("missing_size")
    if fill_price(fill) is None:
        notes.append("missing_price")
    if fill_timestamp(fill) == 0:
        notes.append("missing_timestamp")
    if not has_start_position:
        notes.append("missing_start_position")

    if direction_unclear or fill_size(fill) is None:
        return 0.2, notes
    score = 0.95 if has_start_position else 0.65
    if fill_price(fill) is None:
        score -= 0.15
    if fill_timestamp(fill) == 0:
        score -= 0.10
    return max(0.1, min(1.0, score)), notes


def build_position_delta_from_fill(
    wallet_address: str,
    fill: dict[str, Any],
    *,
    previous_size: float | None = None,
) -> PositionDeltaRecord:
    start = start_position(fill)
    has_start = start is not None
    signed_size = signed_fill_size(fill)
    direction_unclear = signed_size is None

    if has_start:
        effective_previous = start
    elif previous_size is not None:
        effective_previous = previous_size
    else:
        effective_previous = 0.0

    effective_new = effective_previous if signed_size is None else effective_previous + signed_size
    price = fill_price(fill)
    size = abs(signed_size) if signed_size is not None else fill_size(fill)
    delta_notional = abs(effective_new - effective_previous) * price if price is not None else None
    confidence_score, notes = confidence_for_fill(
        fill,
        direction_unclear=direction_unclear,
        has_start_position=has_start,
    )

    return PositionDeltaRecord(
        wallet_address=wallet_address,
        coin=fill_coin(fill),
        previous_side=position_side(effective_previous),
        new_side=position_side(effective_new) if not direction_unclear else PositionSide.UNKNOWN,
        previous_size=effective_previous,
        new_size=effective_new,
        delta_size=effective_new - effective_previous,
        delta_notional_usdc=delta_notional,
        action=classify_action(effective_previous, effective_new, direction_unclear=direction_unclear),
        exchange_ts=fill_timestamp(fill) or None,
        side=str(first_present(fill, "side")) if first_present(fill, "side") is not None else None,
        price=price,
        fill_size=size,
        confidence_score=confidence_score,
        notes=notes,
        raw=fill,
    )
