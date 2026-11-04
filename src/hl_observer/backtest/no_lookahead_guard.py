"""No-lookahead guard (V12 capability J - backtest sans fuite du futur).

A backtest/replay decision may only use data timestamped at or before the decision
time (optionally older, to model latency). Using data newer than the decision is a
"lookahead" leak and silently inflates results. This guard detects such leaks.

Pure / deterministic: takes timestamps, returns violations. No I/O, no order.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any, Iterable, Mapping, Sequence


@dataclass(frozen=True, slots=True)
class LookaheadViolation:
    index: int
    decision_ts_ms: int
    data_ts_ms: int
    detail: str

    def __str__(self) -> str:
        return f"#{self.index}: {self.detail}"


def _pair(ev) -> tuple[int, int]:
    if isinstance(ev, dict):
        return int(ev["decision_ts_ms"]), int(ev["data_ts_ms"])
    decision_ts_ms, data_ts_ms = ev
    return int(decision_ts_ms), int(data_ts_ms)


def find_lookahead_violations(events, *, min_gap_ms: int = 0) -> list[LookaheadViolation]:
    """Return events whose data is newer than allowed.

    A decision at T may use data with ts <= T - min_gap_ms. With min_gap_ms=0 that is
    simply ts <= T; a positive gap also forbids using data more recent than the latency.
    """
    out: list[LookaheadViolation] = []
    if isinstance(min_gap_ms, bool) or int(min_gap_ms) < 0:
        raise ValueError("min_gap_ms must be non-negative")
    gap = int(min_gap_ms)
    for i, ev in enumerate(events):
        d_ts, x_ts = _pair(ev)
        cutoff = d_ts - gap
        if x_ts > cutoff:
            out.append(LookaheadViolation(
                index=i,
                decision_ts_ms=d_ts,
                data_ts_ms=x_ts,
                detail=f"data_ts={x_ts} > cutoff={cutoff} (decision={d_ts}, gap={gap})",
            ))
    return out


def assert_no_lookahead(events, *, min_gap_ms: int = 0) -> None:
    v = find_lookahead_violations(events, min_gap_ms=min_gap_ms)
    if v:
        raise AssertionError(
            f"lookahead leak in {len(v)} event(s): " + "; ".join(str(x) for x in v[:5])
        )


__all__ = [
    "LookaheadViolation", "find_lookahead_violations", "assert_no_lookahead",
    "lookahead_safety_receipt", "lookahead_required_field_receipt",
    "lookahead_null_field_receipt", "lookahead_field_type_receipt",
    "lookahead_finite_receipt", "lookahead_cutoff_receipt", "lookahead_age_receipt",
    "lookahead_duplicate_receipt", "lookahead_retry_receipt", "lookahead_replay_receipt",
    "lookahead_fill_duplicate_receipt", "lookahead_rejection_no_debit_receipt",
    "lookahead_partial_close_receipt", "lookahead_total_close_release_receipt",
    "lookahead_mark_liquidability_receipt", "lookahead_balance_receipt",
    "lookahead_funding_sign_receipt", "lookahead_conversion_receipt",
    "lookahead_commit_receipt", "lookahead_concurrent_write_receipt",
]


def _lookahead_base(status: str, **values: Any) -> dict[str, Any]:
    return {
        "status": status,
        "paper_read_only": True,
        "real_execution": False,
        "promotion": "DISABLED_UNTIL_REVIEW",
        **values,
    }


def _lookahead_integer(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _lookahead_finite(value: Any) -> bool:
    try:
        return math.isfinite(float(value))
    except (TypeError, ValueError, OverflowError):
        return False


def lookahead_safety_receipt(result: Any) -> dict[str, Any]:
    """Prove only that a lookahead audit is clean and structurally complete."""
    violations = result if isinstance(result, Sequence) and not isinstance(result, (str, bytes, bytearray)) else ()
    valid = isinstance(result, Sequence) and not isinstance(result, (str, bytes, bytearray)) and not violations
    return _lookahead_base(
        "PROVEN" if valid else "REJECTED",
        verdict="NO_LOOKAHEAD" if valid else "LOOKAHEAD_OR_INVALID_RESULT",
        violation_count=len(violations),
        fail_closed=not valid,
    )


def lookahead_required_field_receipt(row: Mapping[str, Any], *, field: str) -> dict[str, Any]:
    valid = isinstance(row, Mapping) and isinstance(field, str) and bool(field) and row.get(field) not in (None, "")
    return _lookahead_base("PROVEN" if valid else "REJECTED", verdict="LOOKAHEAD_FIELD_PRESENT" if valid else "LOOKAHEAD_FIELD_MISSING", field=field, fail_closed=not valid)


def lookahead_null_field_receipt(row: Mapping[str, Any], *, field: str) -> dict[str, Any]:
    valid = isinstance(row, Mapping) and isinstance(field, str) and bool(field) and row.get(field) is not None
    return _lookahead_base("PROVEN" if valid else "REJECTED", verdict="LOOKAHEAD_FIELD_NON_NULL" if valid else "LOOKAHEAD_FIELD_NULL", field=field, fail_closed=not valid)


def lookahead_field_type_receipt(row: Mapping[str, Any], *, field: str, expected_type: type) -> dict[str, Any]:
    valid = isinstance(row, Mapping) and isinstance(expected_type, type) and isinstance(row.get(field), expected_type)
    return _lookahead_base("PROVEN" if valid else "REJECTED", verdict="LOOKAHEAD_FIELD_TYPE_VALID" if valid else "LOOKAHEAD_FIELD_TYPE_INVALID", field=field, fail_closed=not valid)


def lookahead_finite_receipt(value: Any) -> dict[str, Any]:
    valid = _lookahead_finite(value)
    return _lookahead_base("PROVEN" if valid else "REJECTED", verdict="LOOKAHEAD_VALUE_FINITE" if valid else "LOOKAHEAD_VALUE_NON_FINITE", value=float(value) if valid else None, fail_closed=not valid)


def lookahead_cutoff_receipt(*, event_ts_ms: Any, cutoff_ts_ms: Any) -> dict[str, Any]:
    valid = _lookahead_integer(event_ts_ms) and _lookahead_integer(cutoff_ts_ms) and event_ts_ms <= cutoff_ts_ms
    return _lookahead_base("PROVEN" if valid else "REJECTED", verdict="LOOKAHEAD_EVENT_WITHIN_CUTOFF" if valid else "LOOKAHEAD_EVENT_AFTER_CUTOFF", fail_closed=not valid)


def lookahead_age_receipt(*, event_ts_ms: Any, oldest_allowed_ts_ms: Any) -> dict[str, Any]:
    valid = _lookahead_integer(event_ts_ms) and _lookahead_integer(oldest_allowed_ts_ms) and event_ts_ms >= oldest_allowed_ts_ms
    return _lookahead_base("PROVEN" if valid else "REJECTED", verdict="LOOKAHEAD_EVENT_AGE_VALID" if valid else "LOOKAHEAD_EVENT_TOO_OLD", fail_closed=not valid)


def lookahead_duplicate_receipt(*, event_ids: Iterable[Any]) -> dict[str, Any]:
    values = list(event_ids)
    valid = bool(values) and all(str(value).strip() for value in values) and len(values) == len(set(values))
    return _lookahead_base("PROVEN" if valid else "REJECTED", verdict="LOOKAHEAD_EVENTS_UNIQUE" if valid else "LOOKAHEAD_EVENT_DUPLICATE_OR_EMPTY", fail_closed=not valid)


def lookahead_retry_receipt(*, attempts: Any, max_attempts: Any, checkpoint_saved: bool) -> dict[str, Any]:
    valid = _lookahead_integer(attempts) and _lookahead_integer(max_attempts) and 1 <= attempts <= max_attempts and checkpoint_saved is True
    return _lookahead_base("PROVEN" if valid else "REJECTED", verdict="LOOKAHEAD_RETRY_BOUNDED" if valid else "LOOKAHEAD_RETRY_UNSAFE", fail_closed=not valid)


def lookahead_replay_receipt(*, outputs: Sequence[Any]) -> dict[str, Any]:
    valid = bool(outputs) and len({repr(value) for value in outputs}) == 1
    return _lookahead_base("PROVEN" if valid else "REJECTED", verdict="LOOKAHEAD_REPLAY_DETERMINISTIC" if valid else "LOOKAHEAD_REPLAY_DIVERGED", fail_closed=not valid)


def lookahead_fill_duplicate_receipt(*, fill_ids: Sequence[Any]) -> dict[str, Any]:
    valid = bool(fill_ids) and all(str(value).strip() for value in fill_ids) and len(fill_ids) == len(set(fill_ids))
    return _lookahead_base("PROVEN" if valid else "REJECTED", verdict="LOOKAHEAD_FILLS_UNIQUE" if valid else "LOOKAHEAD_FILL_DUPLICATED", fail_closed=not valid)


def lookahead_rejection_no_debit_receipt(*, rejected: bool, debited: bool) -> dict[str, Any]:
    valid = rejected is True and debited is False
    return _lookahead_base("PROVEN" if valid else "REJECTED", verdict="LOOKAHEAD_REJECTION_NO_DEBIT" if valid else "LOOKAHEAD_REJECTION_DEBITED", fail_closed=not valid)


def lookahead_partial_close_receipt(*, close_quantity: Any, open_quantity: Any, fee_known: bool, fee_amount: Any) -> dict[str, Any]:
    close = float(close_quantity) if _lookahead_finite(close_quantity) else None
    open_size = float(open_quantity) if _lookahead_finite(open_quantity) else None
    fee = float(fee_amount) if _lookahead_finite(fee_amount) else None
    valid = close is not None and open_size is not None and fee is not None and fee_known is True and 0 < close < open_size and fee >= 0
    return _lookahead_base("PROVEN" if valid else "REJECTED", verdict="LOOKAHEAD_PARTIAL_CLOSE_COSTED" if valid else "LOOKAHEAD_PARTIAL_CLOSE_UNSAFE", fail_closed=not valid)


def lookahead_total_close_release_receipt(*, close_quantity: Any, open_quantity: Any, released_margin: Any) -> dict[str, Any]:
    close = float(close_quantity) if _lookahead_finite(close_quantity) else None
    open_size = float(open_quantity) if _lookahead_finite(open_quantity) else None
    release = float(released_margin) if _lookahead_finite(released_margin) else None
    valid = close is not None and open_size is not None and release is not None and open_size > 0 and abs(close - open_size) <= 1e-12 and release >= 0
    return _lookahead_base("PROVEN" if valid else "REJECTED", verdict="LOOKAHEAD_TOTAL_CLOSE_RELEASED" if valid else "LOOKAHEAD_TOTAL_CLOSE_NOT_RELEASED", fail_closed=not valid)


def lookahead_mark_liquidability_receipt(*, mark_price: Any, bid: Any, ask: Any) -> dict[str, Any]:
    mark = float(mark_price) if _lookahead_finite(mark_price) else None
    best_bid = float(bid) if _lookahead_finite(bid) else None
    best_ask = float(ask) if _lookahead_finite(ask) else None
    valid = mark is not None and best_bid is not None and best_ask is not None and best_bid > 0 and best_ask >= best_bid and best_bid <= mark <= best_ask
    return _lookahead_base("PROVEN" if valid else "REJECTED", verdict="LOOKAHEAD_MARK_LIQUIDABLE" if valid else "LOOKAHEAD_MARK_NOT_LIQUIDABLE", fail_closed=not valid)


def lookahead_balance_receipt(*, balance: Any) -> dict[str, Any]:
    value = float(balance) if _lookahead_finite(balance) else None
    valid = value is not None and value >= 0
    return _lookahead_base("PROVEN" if valid else "REJECTED", verdict="LOOKAHEAD_BALANCE_NON_NEGATIVE" if valid else "LOOKAHEAD_BALANCE_NEGATIVE", fail_closed=not valid)


def lookahead_funding_sign_receipt(*, amount: Any, direction: str) -> dict[str, Any]:
    value = float(amount) if _lookahead_finite(amount) else None
    normalized = str(direction or "").strip().upper()
    valid = value is not None and ((normalized == "CREDIT" and value >= 0) or (normalized == "DEBIT" and value <= 0))
    return _lookahead_base("PROVEN" if valid else "REJECTED", verdict="LOOKAHEAD_FUNDING_SIGN_VALID" if valid else "LOOKAHEAD_FUNDING_SIGN_INVALID", fail_closed=not valid)


def lookahead_conversion_receipt(*, fee_amount: Any, fee_token: Any, pnl_currency: Any, token_to_pnl_rate: Any) -> dict[str, Any]:
    amount = float(fee_amount) if _lookahead_finite(fee_amount) else None
    rate = float(token_to_pnl_rate) if _lookahead_finite(token_to_pnl_rate) else None
    valid = amount is not None and amount >= 0 and rate is not None and rate >= 0 and isinstance(fee_token, str) and bool(fee_token.strip()) and isinstance(pnl_currency, str) and bool(pnl_currency.strip())
    return _lookahead_base("PROVEN" if valid else "REJECTED", verdict="LOOKAHEAD_CONVERSION_PROVEN" if valid else "LOOKAHEAD_CONVERSION_MISSING", fail_closed=not valid)


def lookahead_commit_receipt(*, crashed: bool, committed: bool, checkpoint_saved: bool) -> dict[str, Any]:
    valid = (crashed is True and committed is False and checkpoint_saved is True) or (crashed is False and committed is True)
    return _lookahead_base("PROVEN" if valid else "REJECTED", verdict="LOOKAHEAD_COMMIT_ATOMIC" if valid else "LOOKAHEAD_COMMIT_PARTIAL", fail_closed=not valid)


def lookahead_concurrent_write_receipt(*, write_ids: Sequence[Any]) -> dict[str, Any]:
    valid = bool(write_ids) and all(str(value).strip() for value in write_ids) and len(write_ids) == len(set(write_ids))
    return _lookahead_base("PROVEN" if valid else "REJECTED", verdict="LOOKAHEAD_WRITES_UNIQUE" if valid else "LOOKAHEAD_DOUBLE_WRITE", fail_closed=not valid)
