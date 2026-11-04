"""Execution realism primitives for paper-only backtests."""
from __future__ import annotations

import math
from typing import Any, Iterable, Mapping, Sequence


def _finite_non_negative(*values: float) -> bool:
    return all(
        not isinstance(value, bool)
        and math.isfinite(float(value))
        and float(value) >= 0.0
        for value in values
    )


def maker_fill_probability(
    *, queue_ahead_notional: float, incoming_flow_notional: float, base: float = 0.9
) -> float:
    if not _finite_non_negative(queue_ahead_notional, incoming_flow_notional, base):
        raise ValueError("fill inputs must be finite and non-negative")
    if not 0.0 <= float(base) <= 1.0:
        raise ValueError("base must be in [0, 1]")
    queue = float(queue_ahead_notional)
    flow = float(incoming_flow_notional)
    if flow <= 0:
        return 0.0
    return round(max(0.0, min(1.0, float(base) * flow / (queue + flow))), 6)


def adverse_selection_penalty_bps(
    volatility_bps: float, *, toxicity: float = 0.5
) -> float:
    if not _finite_non_negative(volatility_bps, toxicity):
        raise ValueError("adverse selection inputs must be finite and non-negative")
    return round(float(volatility_bps) * float(toxicity), 6)


def latency_jitter_ms(
    base_ms: float, *, jitter_frac: float = 0.3, sample: float = 0.5
) -> float:
    if (
        not _finite_non_negative(base_ms, jitter_frac)
        or isinstance(sample, bool)
        or not math.isfinite(float(sample))
        or not 0.0 <= float(sample) <= 1.0
    ):
        raise ValueError("latency jitter inputs are invalid")
    return round(
        float(base_ms)
        * (1.0 + float(jitter_frac) * (2.0 * float(sample) - 1.0)),
        3,
    )


__all__ = [
    "maker_fill_probability",
    "adverse_selection_penalty_bps",
    "latency_jitter_ms",
]


def _execution_base(status: str, **values: Any) -> dict[str, Any]:
    return {"status": status, "paper_read_only": True, "real_execution": False, "promotion": "DISABLED_UNTIL_REVIEW", **values}


def _execution_integer(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _execution_finite(value: Any) -> bool:
    try:
        return math.isfinite(float(value))
    except (TypeError, ValueError, OverflowError):
        return False


def execution_realism_safety_receipt(result: Any) -> dict[str, Any]:
    valid = isinstance(result, Mapping) and result.get("paper_read_only") is not False and result.get("real_execution") is not True
    if valid:
        values = [result.get(key) for key in ("fill_probability", "penalty_bps", "latency_ms") if key in result]
        valid = bool(values) and all(_execution_finite(value) and float(value) >= 0 for value in values)
    return _execution_base("PROVEN" if valid else "REJECTED", verdict="EXECUTION_REALISM_SAFE" if valid else "EXECUTION_REALISM_UNSAFE", fail_closed=not valid)


def execution_required_field_receipt(row: Mapping[str, Any], *, field: str) -> dict[str, Any]:
    valid = isinstance(row, Mapping) and isinstance(field, str) and bool(field) and row.get(field) not in (None, "")
    return _execution_base("PROVEN" if valid else "REJECTED", verdict="EXECUTION_FIELD_PRESENT" if valid else "EXECUTION_FIELD_MISSING", field=field, fail_closed=not valid)


def execution_null_field_receipt(row: Mapping[str, Any], *, field: str) -> dict[str, Any]:
    valid = isinstance(row, Mapping) and isinstance(field, str) and bool(field) and row.get(field) is not None
    return _execution_base("PROVEN" if valid else "REJECTED", verdict="EXECUTION_FIELD_NON_NULL" if valid else "EXECUTION_FIELD_NULL", field=field, fail_closed=not valid)


def execution_field_type_receipt(row: Mapping[str, Any], *, field: str, expected_type: type) -> dict[str, Any]:
    valid = isinstance(row, Mapping) and isinstance(expected_type, type) and isinstance(row.get(field), expected_type)
    return _execution_base("PROVEN" if valid else "REJECTED", verdict="EXECUTION_FIELD_TYPE_VALID" if valid else "EXECUTION_FIELD_TYPE_INVALID", field=field, fail_closed=not valid)


def execution_finite_receipt(value: Any) -> dict[str, Any]:
    valid = _execution_finite(value)
    return _execution_base("PROVEN" if valid else "REJECTED", verdict="EXECUTION_VALUE_FINITE" if valid else "EXECUTION_VALUE_NON_FINITE", value=float(value) if valid else None, fail_closed=not valid)


def execution_cutoff_receipt(*, event_ts_ms: Any, cutoff_ts_ms: Any) -> dict[str, Any]:
    valid = _execution_integer(event_ts_ms) and _execution_integer(cutoff_ts_ms) and event_ts_ms <= cutoff_ts_ms
    return _execution_base("PROVEN" if valid else "REJECTED", verdict="EXECUTION_EVENT_WITHIN_CUTOFF" if valid else "EXECUTION_EVENT_AFTER_CUTOFF", fail_closed=not valid)


def execution_age_receipt(*, event_ts_ms: Any, oldest_allowed_ts_ms: Any) -> dict[str, Any]:
    valid = _execution_integer(event_ts_ms) and _execution_integer(oldest_allowed_ts_ms) and event_ts_ms >= oldest_allowed_ts_ms
    return _execution_base("PROVEN" if valid else "REJECTED", verdict="EXECUTION_EVENT_AGE_VALID" if valid else "EXECUTION_EVENT_TOO_OLD", fail_closed=not valid)


def execution_duplicate_receipt(*, event_ids: Iterable[Any]) -> dict[str, Any]:
    values = list(event_ids)
    valid = bool(values) and all(str(value).strip() for value in values) and len(values) == len(set(values))
    return _execution_base("PROVEN" if valid else "REJECTED", verdict="EXECUTION_EVENTS_UNIQUE" if valid else "EXECUTION_EVENT_DUPLICATE_OR_EMPTY", fail_closed=not valid)


def execution_retry_receipt(*, attempts: Any, max_attempts: Any, checkpoint_saved: bool) -> dict[str, Any]:
    valid = _execution_integer(attempts) and _execution_integer(max_attempts) and 1 <= attempts <= max_attempts and checkpoint_saved is True
    return _execution_base("PROVEN" if valid else "REJECTED", verdict="EXECUTION_RETRY_BOUNDED" if valid else "EXECUTION_RETRY_UNSAFE", fail_closed=not valid)


def execution_replay_receipt(*, outputs: Sequence[Any]) -> dict[str, Any]:
    valid = bool(outputs) and len({repr(value) for value in outputs}) == 1
    return _execution_base("PROVEN" if valid else "REJECTED", verdict="EXECUTION_REPLAY_DETERMINISTIC" if valid else "EXECUTION_REPLAY_DIVERGED", fail_closed=not valid)


def execution_fill_duplicate_receipt(*, fill_ids: Sequence[Any]) -> dict[str, Any]:
    valid = bool(fill_ids) and all(str(value).strip() for value in fill_ids) and len(fill_ids) == len(set(fill_ids))
    return _execution_base("PROVEN" if valid else "REJECTED", verdict="EXECUTION_FILLS_UNIQUE" if valid else "EXECUTION_FILL_DUPLICATED", fail_closed=not valid)


def execution_rejection_no_debit_receipt(*, rejected: bool, debited: bool) -> dict[str, Any]:
    valid = rejected is True and debited is False
    return _execution_base("PROVEN" if valid else "REJECTED", verdict="EXECUTION_REJECTION_NO_DEBIT" if valid else "EXECUTION_REJECTION_DEBITED", fail_closed=not valid)


def execution_partial_close_receipt(*, close_quantity: Any, open_quantity: Any, fee_known: bool, fee_amount: Any) -> dict[str, Any]:
    close = float(close_quantity) if _execution_finite(close_quantity) else None
    open_size = float(open_quantity) if _execution_finite(open_quantity) else None
    fee = float(fee_amount) if _execution_finite(fee_amount) else None
    valid = close is not None and open_size is not None and fee is not None and fee_known is True and 0 < close < open_size and fee >= 0
    return _execution_base("PROVEN" if valid else "REJECTED", verdict="EXECUTION_PARTIAL_CLOSE_COSTED" if valid else "EXECUTION_PARTIAL_CLOSE_UNSAFE", fail_closed=not valid)


def execution_total_close_release_receipt(*, close_quantity: Any, open_quantity: Any, released_margin: Any) -> dict[str, Any]:
    close = float(close_quantity) if _execution_finite(close_quantity) else None
    open_size = float(open_quantity) if _execution_finite(open_quantity) else None
    release = float(released_margin) if _execution_finite(released_margin) else None
    valid = close is not None and open_size is not None and release is not None and open_size > 0 and abs(close - open_size) <= 1e-12 and release >= 0
    return _execution_base("PROVEN" if valid else "REJECTED", verdict="EXECUTION_TOTAL_CLOSE_RELEASED" if valid else "EXECUTION_TOTAL_CLOSE_NOT_RELEASED", fail_closed=not valid)


def execution_mark_liquidability_receipt(*, mark_price: Any, bid: Any, ask: Any) -> dict[str, Any]:
    mark = float(mark_price) if _execution_finite(mark_price) else None
    best_bid = float(bid) if _execution_finite(bid) else None
    best_ask = float(ask) if _execution_finite(ask) else None
    valid = mark is not None and best_bid is not None and best_ask is not None and best_bid > 0 and best_ask >= best_bid and best_bid <= mark <= best_ask
    return _execution_base("PROVEN" if valid else "REJECTED", verdict="EXECUTION_MARK_LIQUIDABLE" if valid else "EXECUTION_MARK_NOT_LIQUIDABLE", fail_closed=not valid)


def execution_balance_receipt(*, balance: Any) -> dict[str, Any]:
    value = float(balance) if _execution_finite(balance) else None
    valid = value is not None and value >= 0
    return _execution_base("PROVEN" if valid else "REJECTED", verdict="EXECUTION_BALANCE_NON_NEGATIVE" if valid else "EXECUTION_BALANCE_NEGATIVE", fail_closed=not valid)


def execution_funding_sign_receipt(*, amount: Any, direction: str) -> dict[str, Any]:
    value = float(amount) if _execution_finite(amount) else None
    normalized = str(direction or "").strip().upper()
    valid = value is not None and ((normalized == "CREDIT" and value >= 0) or (normalized == "DEBIT" and value <= 0))
    return _execution_base("PROVEN" if valid else "REJECTED", verdict="EXECUTION_FUNDING_SIGN_VALID" if valid else "EXECUTION_FUNDING_SIGN_INVALID", fail_closed=not valid)


def execution_conversion_receipt(*, fee_amount: Any, fee_token: Any, pnl_currency: Any, token_to_pnl_rate: Any) -> dict[str, Any]:
    amount = float(fee_amount) if _execution_finite(fee_amount) else None
    rate = float(token_to_pnl_rate) if _execution_finite(token_to_pnl_rate) else None
    valid = amount is not None and amount >= 0 and rate is not None and rate >= 0 and isinstance(fee_token, str) and bool(fee_token.strip()) and isinstance(pnl_currency, str) and bool(pnl_currency.strip())
    return _execution_base("PROVEN" if valid else "REJECTED", verdict="EXECUTION_CONVERSION_PROVEN" if valid else "EXECUTION_CONVERSION_MISSING", fail_closed=not valid)


def execution_commit_receipt(*, crashed: bool, committed: bool, checkpoint_saved: bool) -> dict[str, Any]:
    valid = (crashed is True and committed is False and checkpoint_saved is True) or (crashed is False and committed is True)
    return _execution_base("PROVEN" if valid else "REJECTED", verdict="EXECUTION_COMMIT_ATOMIC" if valid else "EXECUTION_COMMIT_PARTIAL", fail_closed=not valid)


def execution_concurrent_write_receipt(*, write_ids: Sequence[Any]) -> dict[str, Any]:
    valid = bool(write_ids) and all(str(value).strip() for value in write_ids) and len(write_ids) == len(set(write_ids))
    return _execution_base("PROVEN" if valid else "REJECTED", verdict="EXECUTION_WRITES_UNIQUE" if valid else "EXECUTION_DOUBLE_WRITE", fail_closed=not valid)


__all__ += [
    "execution_realism_safety_receipt", "execution_required_field_receipt", "execution_null_field_receipt",
    "execution_field_type_receipt", "execution_finite_receipt", "execution_cutoff_receipt", "execution_age_receipt",
    "execution_duplicate_receipt", "execution_retry_receipt", "execution_replay_receipt", "execution_fill_duplicate_receipt",
    "execution_rejection_no_debit_receipt", "execution_partial_close_receipt", "execution_total_close_release_receipt",
    "execution_mark_liquidability_receipt", "execution_balance_receipt", "execution_funding_sign_receipt",
    "execution_conversion_receipt", "execution_commit_receipt", "execution_concurrent_write_receipt",
]
