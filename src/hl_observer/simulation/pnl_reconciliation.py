from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
import math
from typing import Any


@dataclass(frozen=True, slots=True)
class PnlReconciliation:
    ok: bool
    expected_equity_usdc: float
    actual_equity_usdc: float
    diff_usdc: float
    warnings: tuple[str, ...] = field(default_factory=tuple)


def reconcile_pnl(
    *,
    starting_balance_usdc: float,
    realized_pnl_usdc: float,
    unrealized_pnl_usdc: float,
    fees_paid_usdc: float,
    funding_net_usdc: float,
    actual_equity_usdc: float,
    tolerance_usdc: float = 0.0001,
) -> PnlReconciliation:
    values = (
        starting_balance_usdc,
        realized_pnl_usdc,
        unrealized_pnl_usdc,
        fees_paid_usdc,
        funding_net_usdc,
        actual_equity_usdc,
        tolerance_usdc,
    )
    try:
        parsed = tuple(float(value) for value in values)
    except (TypeError, ValueError, OverflowError):
        parsed = ()
    if len(parsed) != len(values) or any(not math.isfinite(value) for value in parsed) or parsed[-1] < 0.0:
        return PnlReconciliation(False, 0.0, 0.0, 0.0, ("PNL_EVIDENCE_NONFINITE",))

    starting, realized, unrealized, fees, funding, actual, tolerance = parsed
    expected = starting + realized + unrealized - fees + funding
    diff = actual - expected
    warnings: list[str] = []
    if abs(diff) > tolerance:
        warnings.append("PNL_RECONCILIATION_MISMATCH")
    return PnlReconciliation(
        ok=not warnings,
        expected_equity_usdc=round(expected, 10),
        actual_equity_usdc=round(actual, 10),
        diff_usdc=round(diff, 10),
        warnings=tuple(warnings),
    )


def realized_mark_receipt(*, realized_pnl_usdc: object, mark_pnl_usdc: object, liquidatable_book: object) -> dict[str, object]:
    """Keep realized PnL separate from mark PnL and require explicit book state."""
    if any(isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(float(value)) for value in (realized_pnl_usdc, mark_pnl_usdc)):
        return {"status": "UNMEASURABLE", "reason": "PNL_COMPONENT_INVALID"}
    if not isinstance(liquidatable_book, bool):
        return {"status": "UNMEASURABLE", "reason": "LIQUIDATABLE_BOOK_FLAG_INVALID"}
    return {"status": "PROVEN", "realized_pnl_usdc": float(realized_pnl_usdc), "mark_pnl_usdc": float(mark_pnl_usdc), "mark_is_unrealized": True, "liquidatable_book": liquidatable_book, "realized_certifiable": liquidatable_book}


def _pnl_base(status: str, **values: Any) -> dict[str, Any]:
    return {"status": status, "paper_read_only": True, "real_execution": False, "promotion": "DISABLED_UNTIL_REVIEW", **values}


def _pnl_integer(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _pnl_finite(value: Any) -> bool:
    if isinstance(value, bool):
        return False
    try:
        return math.isfinite(float(value))
    except (TypeError, ValueError, OverflowError):
        return False


def pnl_reconciliation_safety_receipt(result: PnlReconciliation) -> dict[str, Any]:
    valid = isinstance(result, PnlReconciliation) and all(_pnl_finite(getattr(result, field)) for field in ("expected_equity_usdc", "actual_equity_usdc", "diff_usdc"))
    return _pnl_base("PROVEN" if valid else "REJECTED", verdict="PNL_RECONCILIATION_SAFE" if valid else "PNL_RECONCILIATION_UNSAFE", fail_closed=not valid)


def pnl_required_field_receipt(row: Mapping[str, Any], *, field: str) -> dict[str, Any]:
    valid = isinstance(row, Mapping) and isinstance(field, str) and bool(field) and row.get(field) not in (None, "")
    return _pnl_base("PROVEN" if valid else "REJECTED", verdict="PNL_FIELD_PRESENT" if valid else "PNL_FIELD_MISSING", field=field, fail_closed=not valid)


def pnl_null_field_receipt(row: Mapping[str, Any], *, field: str) -> dict[str, Any]:
    valid = isinstance(row, Mapping) and isinstance(field, str) and bool(field) and row.get(field) is not None
    return _pnl_base("PROVEN" if valid else "REJECTED", verdict="PNL_FIELD_NON_NULL" if valid else "PNL_FIELD_NULL", field=field, fail_closed=not valid)


def pnl_field_type_receipt(row: Mapping[str, Any], *, field: str, expected_type: type) -> dict[str, Any]:
    valid = isinstance(row, Mapping) and isinstance(expected_type, type) and isinstance(row.get(field), expected_type)
    return _pnl_base("PROVEN" if valid else "REJECTED", verdict="PNL_FIELD_TYPE_VALID" if valid else "PNL_FIELD_TYPE_INVALID", field=field, fail_closed=not valid)


def pnl_finite_receipt(value: Any) -> dict[str, Any]:
    valid = _pnl_finite(value)
    return _pnl_base("PROVEN" if valid else "REJECTED", verdict="PNL_VALUE_FINITE" if valid else "PNL_VALUE_NON_FINITE", value=float(value) if valid else None, fail_closed=not valid)


def pnl_cutoff_receipt(*, event_ts_ms: Any, cutoff_ts_ms: Any) -> dict[str, Any]:
    valid = _pnl_integer(event_ts_ms) and _pnl_integer(cutoff_ts_ms) and event_ts_ms <= cutoff_ts_ms
    return _pnl_base("PROVEN" if valid else "REJECTED", verdict="PNL_EVENT_WITHIN_CUTOFF" if valid else "PNL_EVENT_AFTER_CUTOFF", fail_closed=not valid)


def pnl_age_receipt(*, event_ts_ms: Any, oldest_allowed_ts_ms: Any) -> dict[str, Any]:
    valid = _pnl_integer(event_ts_ms) and _pnl_integer(oldest_allowed_ts_ms) and event_ts_ms >= oldest_allowed_ts_ms
    return _pnl_base("PROVEN" if valid else "REJECTED", verdict="PNL_EVENT_AGE_VALID" if valid else "PNL_EVENT_TOO_OLD", fail_closed=not valid)


def pnl_duplicate_receipt(*, event_ids: Sequence[Any]) -> dict[str, Any]:
    valid = bool(event_ids) and all(str(value).strip() for value in event_ids) and len(event_ids) == len(set(event_ids))
    return _pnl_base("PROVEN" if valid else "REJECTED", verdict="PNL_EVENTS_UNIQUE" if valid else "PNL_EVENT_DUPLICATE_OR_EMPTY", fail_closed=not valid)


def pnl_retry_receipt(*, attempts: Any, max_attempts: Any, checkpoint_saved: bool) -> dict[str, Any]:
    valid = _pnl_integer(attempts) and _pnl_integer(max_attempts) and 1 <= attempts <= max_attempts and checkpoint_saved is True
    return _pnl_base("PROVEN" if valid else "REJECTED", verdict="PNL_RETRY_BOUNDED" if valid else "PNL_RETRY_UNSAFE", fail_closed=not valid)


def pnl_replay_receipt(*, outputs: Sequence[Any]) -> dict[str, Any]:
    valid = bool(outputs) and len({repr(value) for value in outputs}) == 1
    return _pnl_base("PROVEN" if valid else "REJECTED", verdict="PNL_REPLAY_DETERMINISTIC" if valid else "PNL_REPLAY_DIVERGED", fail_closed=not valid)


def pnl_fill_duplicate_receipt(*, fill_ids: Sequence[Any]) -> dict[str, Any]:
    valid = bool(fill_ids) and all(str(value).strip() for value in fill_ids) and len(fill_ids) == len(set(fill_ids))
    return _pnl_base("PROVEN" if valid else "REJECTED", verdict="PNL_FILLS_UNIQUE" if valid else "PNL_FILL_DUPLICATED", fail_closed=not valid)


def pnl_rejection_no_debit_receipt(*, rejected: bool, debited: bool) -> dict[str, Any]:
    valid = rejected is True and debited is False
    return _pnl_base("PROVEN" if valid else "REJECTED", verdict="PNL_REJECTION_NO_DEBIT" if valid else "PNL_REJECTION_DEBITED", fail_closed=not valid)


def pnl_partial_close_receipt(*, close_quantity: Any, open_quantity: Any, fee_known: bool, fee_amount: Any) -> dict[str, Any]:
    values = tuple(float(value) if _pnl_finite(value) else None for value in (close_quantity, open_quantity, fee_amount))
    close, open_size, fee = values
    valid = close is not None and open_size is not None and fee is not None and fee_known is True and 0 < close < open_size and fee >= 0
    return _pnl_base("PROVEN" if valid else "REJECTED", verdict="PNL_PARTIAL_CLOSE_COSTED" if valid else "PNL_PARTIAL_CLOSE_UNSAFE", fail_closed=not valid)


def pnl_total_close_release_receipt(*, close_quantity: Any, open_quantity: Any, released_margin: Any) -> dict[str, Any]:
    values = tuple(float(value) if _pnl_finite(value) else None for value in (close_quantity, open_quantity, released_margin))
    close, open_size, release = values
    valid = close is not None and open_size is not None and release is not None and open_size > 0 and abs(close - open_size) <= 1e-12 and release >= 0
    return _pnl_base("PROVEN" if valid else "REJECTED", verdict="PNL_TOTAL_CLOSE_RELEASED" if valid else "PNL_TOTAL_CLOSE_NOT_RELEASED", fail_closed=not valid)


def pnl_mark_liquidability_receipt(*, mark_price: Any, bid: Any, ask: Any) -> dict[str, Any]:
    values = tuple(float(value) if _pnl_finite(value) else None for value in (mark_price, bid, ask))
    mark, best_bid, best_ask = values
    valid = mark is not None and best_bid is not None and best_ask is not None and best_bid > 0 and best_ask >= best_bid and best_bid <= mark <= best_ask
    return _pnl_base("PROVEN" if valid else "REJECTED", verdict="PNL_MARK_LIQUIDABLE" if valid else "PNL_MARK_NOT_LIQUIDABLE", fail_closed=not valid)


def pnl_balance_receipt(*, balance: Any) -> dict[str, Any]:
    value = float(balance) if _pnl_finite(balance) else None
    valid = value is not None and value >= 0
    return _pnl_base("PROVEN" if valid else "REJECTED", verdict="PNL_BALANCE_NON_NEGATIVE" if valid else "PNL_BALANCE_NEGATIVE", fail_closed=not valid)


def pnl_funding_sign_receipt(*, amount: Any, direction: str) -> dict[str, Any]:
    value = float(amount) if _pnl_finite(amount) else None
    normalized = str(direction or "").strip().upper()
    valid = value is not None and ((normalized == "CREDIT" and value >= 0) or (normalized == "DEBIT" and value <= 0))
    return _pnl_base("PROVEN" if valid else "REJECTED", verdict="PNL_FUNDING_SIGN_VALID" if valid else "PNL_FUNDING_SIGN_INVALID", fail_closed=not valid)


def pnl_conversion_receipt(*, fee_amount: Any, fee_token: Any, pnl_currency: Any, token_to_pnl_rate: Any) -> dict[str, Any]:
    amount = float(fee_amount) if _pnl_finite(fee_amount) else None
    rate = float(token_to_pnl_rate) if _pnl_finite(token_to_pnl_rate) else None
    valid = amount is not None and amount >= 0 and rate is not None and rate >= 0 and isinstance(fee_token, str) and bool(fee_token.strip()) and isinstance(pnl_currency, str) and bool(pnl_currency.strip())
    return _pnl_base("PROVEN" if valid else "REJECTED", verdict="PNL_CONVERSION_PROVEN" if valid else "PNL_CONVERSION_MISSING", fail_closed=not valid)


def pnl_commit_receipt(*, crashed: bool, committed: bool, checkpoint_saved: bool) -> dict[str, Any]:
    valid = (crashed is True and committed is False and checkpoint_saved is True) or (crashed is False and committed is True)
    return _pnl_base("PROVEN" if valid else "REJECTED", verdict="PNL_COMMIT_ATOMIC" if valid else "PNL_COMMIT_PARTIAL", fail_closed=not valid)


def pnl_concurrent_write_receipt(*, write_ids: Sequence[Any]) -> dict[str, Any]:
    valid = bool(write_ids) and all(str(value).strip() for value in write_ids) and len(write_ids) == len(set(write_ids))
    return _pnl_base("PROVEN" if valid else "REJECTED", verdict="PNL_WRITES_UNIQUE" if valid else "PNL_DOUBLE_WRITE", fail_closed=not valid)


__all__ = [
    "PnlReconciliation", "reconcile_pnl", "realized_mark_receipt",
    "pnl_reconciliation_safety_receipt", "pnl_required_field_receipt", "pnl_null_field_receipt",
    "pnl_field_type_receipt", "pnl_finite_receipt", "pnl_cutoff_receipt", "pnl_age_receipt",
    "pnl_duplicate_receipt", "pnl_retry_receipt", "pnl_replay_receipt", "pnl_fill_duplicate_receipt",
    "pnl_rejection_no_debit_receipt", "pnl_partial_close_receipt", "pnl_total_close_release_receipt",
    "pnl_mark_liquidability_receipt", "pnl_balance_receipt", "pnl_funding_sign_receipt",
    "pnl_conversion_receipt", "pnl_commit_receipt", "pnl_concurrent_write_receipt",
]
