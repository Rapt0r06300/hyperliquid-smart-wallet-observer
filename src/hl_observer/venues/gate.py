"""Gate.io capability declaration; live market data lives in collection.gate_market_data."""
from __future__ import annotations

import math
from decimal import Decimal, InvalidOperation
from typing import Any, Mapping, Sequence

VENUE = "gate"


def _gate_base(status: str, **values: Any) -> dict[str, Any]:
    return {
        "status": status,
        "paper_read_only": True,
        "real_execution": False,
        "promotion": "DISABLED_UNTIL_REVIEW",
        **values,
    }


def _gate_integer(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _gate_finite(value: Any) -> bool:
    try:
        return math.isfinite(float(value))
    except (TypeError, ValueError, OverflowError):
        return False


def gate_safety_receipt(capability: Mapping[str, Any]) -> dict[str, Any]:
    valid = (
        isinstance(capability, Mapping)
        and capability.get("venue") == VENUE
        and capability.get("adaptateur") == "OFFLINE_READY"
        and capability.get("pull_live") == "REQUIRES_NETWORK"
        and "book" in tuple(capability.get("flux") or ())
    )
    return _gate_base("PROVEN" if valid else "REJECTED", verdict="GATE_OFFLINE_L2_CAPABILITY" if valid else "GATE_UNSAFE_CAPABILITY", fail_closed=not valid)


def gate_required_field_receipt(row: Mapping[str, Any], *, field: str) -> dict[str, Any]:
    valid = isinstance(row, Mapping) and isinstance(field, str) and bool(field) and row.get(field) not in (None, "")
    return _gate_base("PROVEN" if valid else "REJECTED", verdict="GATE_FIELD_PRESENT" if valid else "GATE_FIELD_MISSING", field=field, fail_closed=not valid)


def gate_null_field_receipt(row: Mapping[str, Any], *, field: str) -> dict[str, Any]:
    valid = isinstance(row, Mapping) and isinstance(field, str) and bool(field) and row.get(field) is not None
    return _gate_base("PROVEN" if valid else "REJECTED", verdict="GATE_FIELD_NON_NULL" if valid else "GATE_FIELD_NULL", field=field, fail_closed=not valid)


def gate_field_type_receipt(row: Mapping[str, Any], *, field: str, expected_type: type) -> dict[str, Any]:
    valid = isinstance(row, Mapping) and isinstance(expected_type, type) and isinstance(row.get(field), expected_type)
    return _gate_base("PROVEN" if valid else "REJECTED", verdict="GATE_FIELD_TYPE_VALID" if valid else "GATE_FIELD_TYPE_INVALID", field=field, fail_closed=not valid)


def gate_finite_receipt(value: Any) -> dict[str, Any]:
    valid = _gate_finite(value)
    return _gate_base("PROVEN" if valid else "REJECTED", verdict="GATE_VALUE_FINITE" if valid else "GATE_VALUE_NON_FINITE", value=float(value) if valid else None, fail_closed=not valid)


def gate_cutoff_receipt(*, event_ts_ms: Any, cutoff_ts_ms: Any) -> dict[str, Any]:
    valid = _gate_integer(event_ts_ms) and _gate_integer(cutoff_ts_ms) and event_ts_ms <= cutoff_ts_ms
    return _gate_base("PROVEN" if valid else "REJECTED", verdict="GATE_EVENT_WITHIN_CUTOFF" if valid else "GATE_EVENT_AFTER_CUTOFF", fail_closed=not valid)


def gate_age_receipt(*, event_ts_ms: Any, oldest_allowed_ts_ms: Any) -> dict[str, Any]:
    valid = _gate_integer(event_ts_ms) and _gate_integer(oldest_allowed_ts_ms) and event_ts_ms >= oldest_allowed_ts_ms
    return _gate_base("PROVEN" if valid else "REJECTED", verdict="GATE_EVENT_AGE_VALID" if valid else "GATE_EVENT_TOO_OLD", fail_closed=not valid)


def gate_duplicate_receipt(*, event_ids: list[Any]) -> dict[str, Any]:
    valid = bool(event_ids) and all(str(value).strip() for value in event_ids) and len(event_ids) == len(set(event_ids))
    return _gate_base("PROVEN" if valid else "REJECTED", verdict="GATE_EVENTS_UNIQUE" if valid else "GATE_EVENT_DUPLICATE_OR_EMPTY", fail_closed=not valid)


def gate_retry_receipt(*, attempts: Any, max_attempts: Any, checkpoint_saved: bool) -> dict[str, Any]:
    valid = _gate_integer(attempts) and _gate_integer(max_attempts) and 1 <= attempts <= max_attempts and checkpoint_saved is True
    return _gate_base("PROVEN" if valid else "REJECTED", verdict="GATE_RETRY_BOUNDED" if valid else "GATE_RETRY_UNSAFE", fail_closed=not valid)


def gate_replay_receipt(*, outputs: list[Any]) -> dict[str, Any]:
    valid = bool(outputs) and len({repr(value) for value in outputs}) == 1
    return _gate_base("PROVEN" if valid else "REJECTED", verdict="GATE_REPLAY_DETERMINISTIC" if valid else "GATE_REPLAY_DIVERGED", fail_closed=not valid)


def gate_depth_receipt(*, bids: Sequence[Sequence[Any]], asks: Sequence[Sequence[Any]], is_bbo: bool) -> dict[str, Any]:
    valid = bool(bids) and bool(asks) and is_bbo is False and all(len(level) >= 2 and _gate_finite(level[0]) and _gate_finite(level[1]) and float(level[1]) > 0 for level in (*bids, *asks))
    return _gate_base("PROVEN" if valid else "REJECTED", verdict="GATE_FULL_DEPTH" if valid else "GATE_BBO_OR_INVALID_DEPTH", fail_closed=not valid)


def gate_crossed_book_receipt(*, best_bid: Any, best_ask: Any) -> dict[str, Any]:
    valid = _gate_finite(best_bid) and _gate_finite(best_ask) and float(best_ask) >= float(best_bid) > 0
    return _gate_base("PROVEN" if valid else "REJECTED", verdict="GATE_BOOK_NOT_CROSSED" if valid else "GATE_BOOK_CROSSED_OR_INVALID", fail_closed=not valid)


def gate_negative_size_receipt(*, sizes: Sequence[Any]) -> dict[str, Any]:
    valid = bool(sizes) and all(_gate_finite(size) and float(size) > 0 for size in sizes)
    return _gate_base("PROVEN" if valid else "REJECTED", verdict="GATE_SIZES_POSITIVE" if valid else "GATE_NEGATIVE_OR_ZERO_SIZE", fail_closed=not valid)


def gate_tick_receipt(*, prices: Sequence[Any], tick_size: Any) -> dict[str, Any]:
    try:
        tick = Decimal(str(tick_size))
        valid = tick > 0 and bool(prices) and all(Decimal(str(price)) % tick == 0 for price in prices)
    except (InvalidOperation, TypeError, ValueError, OverflowError):
        valid = False
    return _gate_base("PROVEN" if valid else "REJECTED", verdict="GATE_TICK_ALIGNED" if valid else "GATE_TICK_INVALID", fail_closed=not valid)


def gate_delta_receipt(*, has_snapshot: bool, delta_count: Any) -> dict[str, Any]:
    valid = has_snapshot is True and _gate_integer(delta_count) and delta_count > 0
    return _gate_base("PROVEN" if valid else "REJECTED", verdict="GATE_DELTA_HAS_SNAPSHOT" if valid else "GATE_DELTA_WITHOUT_SNAPSHOT", fail_closed=not valid)


def gate_staleness_receipt(*, now_ms: Any, received_ts_ms: Any, max_age_ms: Any) -> dict[str, Any]:
    valid = all(_gate_integer(value) for value in (now_ms, received_ts_ms, max_age_ms)) and now_ms >= received_ts_ms and now_ms - received_ts_ms <= max_age_ms
    return _gate_base("PROVEN" if valid else "REJECTED", verdict="GATE_FRESH" if valid else "GATE_STALE", fail_closed=not valid)


def gate_quantity_receipt(*, requested_quantity: Any, visible_depth: Any) -> dict[str, Any]:
    valid = _gate_finite(requested_quantity) and _gate_finite(visible_depth) and 0 < float(requested_quantity) <= float(visible_depth)
    return _gate_base("PROVEN" if valid else "REJECTED", verdict="GATE_QUANTITY_WITHIN_DEPTH" if valid else "GATE_QUANTITY_EXCEEDS_DEPTH", fail_closed=not valid)


def gate_consumption_receipt(*, consumed_quantity: Any, available_quantity: Any, already_consumed: Any) -> dict[str, Any]:
    valid = all(_gate_finite(value) for value in (consumed_quantity, available_quantity, already_consumed)) and min(float(consumed_quantity), float(available_quantity), float(already_consumed)) >= 0 and float(consumed_quantity) + float(already_consumed) <= float(available_quantity)
    return _gate_base("PROVEN" if valid else "REJECTED", verdict="GATE_CONSUMPTION_ONCE" if valid else "GATE_DOUBLE_CONSUMPTION", fail_closed=not valid)


def gate_maker_touch_receipt(*, touched: bool, executed: bool) -> dict[str, Any]:
    valid = touched is False or executed is True
    return _gate_base("PROVEN" if valid else "REJECTED", verdict="GATE_MAKER_EXECUTION_CONFIRMED" if valid else "GATE_TOUCH_ONLY_NOT_FILL", fail_closed=not valid)


def gate_fee_order_receipt(*, maker_fee_bps: Any, taker_fee_bps: Any) -> dict[str, Any]:
    valid = _gate_finite(maker_fee_bps) and _gate_finite(taker_fee_bps) and float(maker_fee_bps) >= 0 and float(taker_fee_bps) >= float(maker_fee_bps)
    return _gate_base("PROVEN" if valid else "REJECTED", verdict="GATE_FEE_ORDER_VALID" if valid else "GATE_FEE_ORDER_INVERTED", fail_closed=not valid)


def capacites() -> dict:
    return {"venue": VENUE, "flux": ("book", "trades", "ticker", "funding", "oi", "mark", "index"), "adaptateur": "OFFLINE_READY", "pull_live": "REQUIRES_NETWORK"}
