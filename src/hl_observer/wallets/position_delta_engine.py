from __future__ import annotations

import math

try:
    from enum import StrEnum
except ImportError:
    from enum import Enum

    class StrEnum(str, Enum):
        pass
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
    LIQUIDATION = "LIQUIDATION"
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
    exchange_ts: int | None = None
    fill_id: int | None = None
    source_event_id: int | None = None
    side: str | None = None
    price: float | None = None
    fill_size: float | None = None
    confidence_score: float = 0.0
    is_paper_eligible: bool = False
    snapshot_id: int | None = None
    proofs: dict[str, bool] = Field(default_factory=dict)
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


def public_fill_payload(fill: dict[str, Any]) -> dict[str, Any]:
    """Drop local observer metadata before hashing/storing external fill payloads."""

    return {key: value for key, value in fill.items() if not str(key).startswith("_hypersmart_")}


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
    value = safe_float(first_present(fill, "startPosition", "start_position"))
    return value if value is not None and math.isfinite(value) else None


_FILL_SIDE_SIGNS = {
    "b": 1, "buy": 1, "bid": 1,
    "a": -1, "s": -1, "sell": -1, "ask": -1,
}
_DIR_FILL_SIGNS = {
    "open long": 1,
    "close short": 1,
    "reduce short": 1,
    "liquidated short": 1,
    "open short": -1,
    "close long": -1,
    "reduce long": -1,
    "liquidated long": -1,
}


def fill_side_sign(fill: dict[str, Any]) -> int | None:
    """Return signed movement from the venue's economic ``side`` field only."""

    side = str(first_present(fill, "side") or "").strip().casefold()
    return _FILL_SIDE_SIGNS.get(side)


def fill_direction_validation(fill: dict[str, Any]) -> str:
    """Check display ``dir`` against ``side``; never derive trade side from its label."""

    sign = fill_side_sign(fill)
    if sign is None:
        return "FILL_SIDE_INVALID"
    label = " ".join(str(first_present(fill, "dir", "direction") or "").casefold().split())
    if not label:
        return "DIR_LABEL_MISSING"
    expected_sign = _DIR_FILL_SIGNS.get(label)
    if expected_sign is None:
        return "UNKNOWN_DIR_LABEL"
    return "CONSISTENT" if sign == expected_sign else "FILL_SIDE_DIR_CONTRADICTION"


def signed_fill_size(fill: dict[str, Any]) -> float | None:
    size = fill_size(fill)
    if size is None or not math.isfinite(size) or size <= 0:
        return None
    sign = fill_side_sign(fill)
    if sign is None or fill_direction_validation(fill) == "FILL_SIDE_DIR_CONTRADICTION":
        return None
    return sign * size


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


def detect_liquidation(fill: dict[str, Any] | None) -> bool:
    """True if a real Hyperliquid fill indicates a liquidation (never inferred from size).

    Uses only fields the venue actually provides: a truthy ``liquidation`` field, or a
    direction/side/type string containing 'liquidat'. No fabrication.
    """
    if not isinstance(fill, dict):
        return False
    if fill.get("liquidation"):
        return True
    blob = " ".join(
        str(first_present(fill, key) or "")
        for key in ("dir", "direction", "side", "type")
    ).lower()
    return "liquidat" in blob


def classify_lifecycle(
    previous_size: float,
    new_size: float,
    *,
    fill: dict[str, Any] | None = None,
    direction_unclear: bool = False,
) -> PositionAction:
    """Full V12 lifecycle classification: the base OPEN/ADD/REDUCE/CLOSE/FLIP/UNKNOWN
    states, plus LIQUIDATION when a real fill flags it on a size reduction/close."""
    base = classify_action(previous_size, new_size, direction_unclear=direction_unclear)
    if fill is not None and base in {PositionAction.REDUCE, PositionAction.CLOSE} and detect_liquidation(fill):
        return PositionAction.LIQUIDATION
    return base


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
    raw_start = first_present(fill, "startPosition", "start_position")
    invalid_start = raw_start is not None and start is None
    direction_unclear = signed_size is None or invalid_start

    if has_start:
        effective_previous = start
    elif previous_size is not None:
        effective_previous = previous_size
    else:
        effective_previous = 0.0

    effective_new = (
        effective_previous
        if direction_unclear
        else effective_previous + signed_size
    )
    price = fill_price(fill)
    size = abs(signed_size) if signed_size is not None else fill_size(fill)
    delta_notional = (
        abs(signed_size) * price
        if not direction_unclear and signed_size is not None and price is not None
        else None
    )
    confidence_score, notes = confidence_for_fill(
        fill,
        direction_unclear=direction_unclear,
        has_start_position=has_start,
    )
    if invalid_start:
        notes.append("start_position_invalid")
    direction_validation = fill_direction_validation(fill)
    if direction_validation == "FILL_SIDE_DIR_CONTRADICTION":
        notes.append("side_dir_contradiction")
    elif direction_validation == "FILL_SIDE_INVALID":
        notes.append("fill_side_invalid")
    elif direction_validation == "UNKNOWN_DIR_LABEL":
        notes.append("unknown_dir_label_side_used")
    source = str(first_present(fill, "_hypersmart_source") or "user_fills")
    if source != "user_fills":
        notes.append(f"source:{source}")

    return PositionDeltaRecord(
        wallet_address=wallet_address,
        coin=fill_coin(fill),
        previous_side=position_side(effective_previous),
        new_side=position_side(effective_new) if not direction_unclear else PositionSide.UNKNOWN,
        previous_size=effective_previous,
        new_size=effective_new,
        delta_size=effective_new - effective_previous,
        delta_notional_usdc=delta_notional,
        action=classify_lifecycle(effective_previous, effective_new, fill=fill, direction_unclear=direction_unclear),
        exchange_ts=fill_timestamp(fill) or None,
        side=str(first_present(fill, "side")) if first_present(fill, "side") is not None else None,
        price=price,
        fill_size=size,
        confidence_score=confidence_score,
        is_paper_eligible=confidence_score >= 0.7,
        source=source,
        notes=notes,
        raw=public_fill_payload(fill),
    )
