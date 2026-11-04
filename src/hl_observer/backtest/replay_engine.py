from __future__ import annotations

import math
from typing import Any, Iterable, Mapping, Sequence

def replay_events(raw_events: list[dict]) -> list[dict]:
    return list(raw_events)


def _engine_base(status: str, **values: Any) -> dict[str, Any]:
    return {"status": status, "paper_read_only": True, "real_execution": False, "promotion": "DISABLED_UNTIL_REVIEW", **values}


def _engine_integer(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _engine_finite(value: Any) -> bool:
    try:
        return math.isfinite(float(value))
    except (TypeError, ValueError, OverflowError):
        return False


def replay_engine_safety_receipt(result: Any) -> dict[str, Any]:
    valid = isinstance(result, Sequence) and not isinstance(result, (str, bytes, bytearray)) and bool(result) and all(isinstance(item, Mapping) for item in result)
    if valid:
        timestamps = [item.get("ts_ms") for item in result if "ts_ms" in item]
        valid = len(timestamps) == len(result) and all(_engine_integer(ts) for ts in timestamps) and timestamps == sorted(timestamps)
    return _engine_base("PROVEN" if valid else "REJECTED", verdict="REPLAY_ENGINE_SAFE" if valid else "REPLAY_ENGINE_UNSAFE", fail_closed=not valid)


def engine_required_field_receipt(row: Mapping[str, Any], *, field: str) -> dict[str, Any]:
    valid = isinstance(row, Mapping) and isinstance(field, str) and bool(field) and row.get(field) not in (None, "")
    return _engine_base("PROVEN" if valid else "REJECTED", verdict="ENGINE_FIELD_PRESENT" if valid else "ENGINE_FIELD_MISSING", field=field, fail_closed=not valid)


def engine_null_field_receipt(row: Mapping[str, Any], *, field: str) -> dict[str, Any]:
    valid = isinstance(row, Mapping) and isinstance(field, str) and bool(field) and row.get(field) is not None
    return _engine_base("PROVEN" if valid else "REJECTED", verdict="ENGINE_FIELD_NON_NULL" if valid else "ENGINE_FIELD_NULL", field=field, fail_closed=not valid)


def engine_field_type_receipt(row: Mapping[str, Any], *, field: str, expected_type: type) -> dict[str, Any]:
    valid = isinstance(row, Mapping) and isinstance(expected_type, type) and isinstance(row.get(field), expected_type)
    return _engine_base("PROVEN" if valid else "REJECTED", verdict="ENGINE_FIELD_TYPE_VALID" if valid else "ENGINE_FIELD_TYPE_INVALID", field=field, fail_closed=not valid)


def engine_finite_receipt(value: Any) -> dict[str, Any]:
    valid = _engine_finite(value)
    return _engine_base("PROVEN" if valid else "REJECTED", verdict="ENGINE_VALUE_FINITE" if valid else "ENGINE_VALUE_NON_FINITE", value=float(value) if valid else None, fail_closed=not valid)


def engine_cutoff_receipt(*, event_ts_ms: Any, cutoff_ts_ms: Any) -> dict[str, Any]:
    valid = _engine_integer(event_ts_ms) and _engine_integer(cutoff_ts_ms) and event_ts_ms <= cutoff_ts_ms
    return _engine_base("PROVEN" if valid else "REJECTED", verdict="ENGINE_EVENT_WITHIN_CUTOFF" if valid else "ENGINE_EVENT_AFTER_CUTOFF", fail_closed=not valid)


def engine_age_receipt(*, event_ts_ms: Any, oldest_allowed_ts_ms: Any) -> dict[str, Any]:
    valid = _engine_integer(event_ts_ms) and _engine_integer(oldest_allowed_ts_ms) and event_ts_ms >= oldest_allowed_ts_ms
    return _engine_base("PROVEN" if valid else "REJECTED", verdict="ENGINE_EVENT_AGE_VALID" if valid else "ENGINE_EVENT_TOO_OLD", fail_closed=not valid)


def engine_duplicate_receipt(*, event_ids: Iterable[Any]) -> dict[str, Any]:
    values = list(event_ids)
    valid = bool(values) and all(str(value).strip() for value in values) and len(values) == len(set(values))
    return _engine_base("PROVEN" if valid else "REJECTED", verdict="ENGINE_EVENTS_UNIQUE" if valid else "ENGINE_EVENT_DUPLICATE_OR_EMPTY", fail_closed=not valid)


def engine_retry_receipt(*, attempts: Any, max_attempts: Any, checkpoint_saved: bool) -> dict[str, Any]:
    valid = _engine_integer(attempts) and _engine_integer(max_attempts) and 1 <= attempts <= max_attempts and checkpoint_saved is True
    return _engine_base("PROVEN" if valid else "REJECTED", verdict="ENGINE_RETRY_BOUNDED" if valid else "ENGINE_RETRY_UNSAFE", fail_closed=not valid)


def engine_replay_receipt(*, outputs: Sequence[Any]) -> dict[str, Any]:
    valid = bool(outputs) and len({repr(value) for value in outputs}) == 1
    return _engine_base("PROVEN" if valid else "REJECTED", verdict="ENGINE_REPLAY_DETERMINISTIC" if valid else "ENGINE_REPLAY_DIVERGED", fail_closed=not valid)


def engine_fill_duplicate_receipt(*, fill_ids: Sequence[Any]) -> dict[str, Any]:
    valid = bool(fill_ids) and all(str(value).strip() for value in fill_ids) and len(fill_ids) == len(set(fill_ids))
    return _engine_base("PROVEN" if valid else "REJECTED", verdict="ENGINE_FILLS_UNIQUE" if valid else "ENGINE_FILL_DUPLICATED", fail_closed=not valid)


def engine_rejection_no_debit_receipt(*, rejected: bool, debited: bool) -> dict[str, Any]:
    valid = rejected is True and debited is False
    return _engine_base("PROVEN" if valid else "REJECTED", verdict="ENGINE_REJECTION_NO_DEBIT" if valid else "ENGINE_REJECTION_DEBITED", fail_closed=not valid)


def engine_partial_close_receipt(*, close_quantity: Any, open_quantity: Any, fee_known: bool, fee_amount: Any) -> dict[str, Any]:
    close = float(close_quantity) if _engine_finite(close_quantity) else None
    open_size = float(open_quantity) if _engine_finite(open_quantity) else None
    fee = float(fee_amount) if _engine_finite(fee_amount) else None
    valid = close is not None and open_size is not None and fee is not None and fee_known is True and 0 < close < open_size and fee >= 0
    return _engine_base("PROVEN" if valid else "REJECTED", verdict="ENGINE_PARTIAL_CLOSE_COSTED" if valid else "ENGINE_PARTIAL_CLOSE_UNSAFE", fail_closed=not valid)


def engine_total_close_release_receipt(*, close_quantity: Any, open_quantity: Any, released_margin: Any) -> dict[str, Any]:
    close = float(close_quantity) if _engine_finite(close_quantity) else None
    open_size = float(open_quantity) if _engine_finite(open_quantity) else None
    release = float(released_margin) if _engine_finite(released_margin) else None
    valid = close is not None and open_size is not None and release is not None and open_size > 0 and abs(close - open_size) <= 1e-12 and release >= 0
    return _engine_base("PROVEN" if valid else "REJECTED", verdict="ENGINE_TOTAL_CLOSE_RELEASED" if valid else "ENGINE_TOTAL_CLOSE_NOT_RELEASED", fail_closed=not valid)


def engine_mark_liquidability_receipt(*, mark_price: Any, bid: Any, ask: Any) -> dict[str, Any]:
    mark = float(mark_price) if _engine_finite(mark_price) else None
    best_bid = float(bid) if _engine_finite(bid) else None
    best_ask = float(ask) if _engine_finite(ask) else None
    valid = mark is not None and best_bid is not None and best_ask is not None and best_bid > 0 and best_ask >= best_bid and best_bid <= mark <= best_ask
    return _engine_base("PROVEN" if valid else "REJECTED", verdict="ENGINE_MARK_LIQUIDABLE" if valid else "ENGINE_MARK_NOT_LIQUIDABLE", fail_closed=not valid)


def engine_balance_receipt(*, balance: Any) -> dict[str, Any]:
    value = float(balance) if _engine_finite(balance) else None
    valid = value is not None and value >= 0
    return _engine_base("PROVEN" if valid else "REJECTED", verdict="ENGINE_BALANCE_NON_NEGATIVE" if valid else "ENGINE_BALANCE_NEGATIVE", fail_closed=not valid)


def engine_funding_sign_receipt(*, amount: Any, direction: str) -> dict[str, Any]:
    value = float(amount) if _engine_finite(amount) else None
    normalized = str(direction or "").strip().upper()
    valid = value is not None and ((normalized == "CREDIT" and value >= 0) or (normalized == "DEBIT" and value <= 0))
    return _engine_base("PROVEN" if valid else "REJECTED", verdict="ENGINE_FUNDING_SIGN_VALID" if valid else "ENGINE_FUNDING_SIGN_INVALID", fail_closed=not valid)


def engine_conversion_receipt(*, fee_amount: Any, fee_token: Any, pnl_currency: Any, token_to_pnl_rate: Any) -> dict[str, Any]:
    amount = float(fee_amount) if _engine_finite(fee_amount) else None
    rate = float(token_to_pnl_rate) if _engine_finite(token_to_pnl_rate) else None
    valid = amount is not None and amount >= 0 and rate is not None and rate >= 0 and isinstance(fee_token, str) and bool(fee_token.strip()) and isinstance(pnl_currency, str) and bool(pnl_currency.strip())
    return _engine_base("PROVEN" if valid else "REJECTED", verdict="ENGINE_CONVERSION_PROVEN" if valid else "ENGINE_CONVERSION_MISSING", fail_closed=not valid)


def engine_commit_receipt(*, crashed: bool, committed: bool, checkpoint_saved: bool) -> dict[str, Any]:
    valid = (crashed is True and committed is False and checkpoint_saved is True) or (crashed is False and committed is True)
    return _engine_base("PROVEN" if valid else "REJECTED", verdict="ENGINE_COMMIT_ATOMIC" if valid else "ENGINE_COMMIT_PARTIAL", fail_closed=not valid)


def engine_concurrent_write_receipt(*, write_ids: Sequence[Any]) -> dict[str, Any]:
    valid = bool(write_ids) and all(str(value).strip() for value in write_ids) and len(write_ids) == len(set(write_ids))
    return _engine_base("PROVEN" if valid else "REJECTED", verdict="ENGINE_WRITES_UNIQUE" if valid else "ENGINE_DOUBLE_WRITE", fail_closed=not valid)


__all__ = [
    "replay_events", "replay_engine_safety_receipt", "engine_required_field_receipt",
    "engine_null_field_receipt", "engine_field_type_receipt", "engine_finite_receipt",
    "engine_cutoff_receipt", "engine_age_receipt", "engine_duplicate_receipt",
    "engine_retry_receipt", "engine_replay_receipt", "engine_fill_duplicate_receipt",
    "engine_rejection_no_debit_receipt", "engine_partial_close_receipt",
    "engine_total_close_release_receipt", "engine_mark_liquidability_receipt",
    "engine_balance_receipt", "engine_funding_sign_receipt", "engine_conversion_receipt",
    "engine_commit_receipt", "engine_concurrent_write_receipt",
]
