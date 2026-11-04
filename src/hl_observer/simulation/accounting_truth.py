"""Small, strict helpers for paper-accounting truth.

The live UI, replay jobs, and reports must agree on the same accounting
vocabulary.  This module deliberately contains no strategy decisions and no
network access.
"""

from __future__ import annotations

import json
import math
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, TypeVar

T = TypeVar("T")

ACCOUNTING_SCHEMA_VERSION = "HS_ACCOUNTING_V2"


def first_not_none(*values: T | None) -> T | None:
    """Return the first present value while preserving legitimate zeroes."""

    for value in values:
        if value is not None:
            return value
    return None


def finite_number(value: object) -> float | None:
    """Parse a finite number; unknown and non-finite values stay unknown."""

    if isinstance(value, bool):
        return None
    try:
        parsed = float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError, OverflowError):
        return None
    return parsed if math.isfinite(parsed) else None


def separate_entry_cost_usdc(position: dict[str, Any]) -> float | None:
    """Return the still-unrealized entry cost carried by a paper position.

    ``0`` is returned only when the entry cost is explicitly embedded in the
    recorded entry price or an explicit zero cost is present. Missing cost
    evidence stays ``None`` so callers cannot silently turn an unknown cost
    into free execution.
    """

    if position.get("fee_already_embedded_in_entry_price") is True:
        return 0.0
    raw_cost = first_not_none(
        position.get("entry_costs"),
        position.get("entry_cost_usdc"),
        position.get("entry_costs_usdc"),
    )
    cost = finite_number(raw_cost)
    if cost is None or cost < 0:
        return None
    return cost


def allocated_entry_cost_usdc(
    position: dict[str, Any],
    *,
    close_quantity: object,
    open_quantity: object,
) -> float | None:
    """Allocate a position's carried entry cost to an exact close quantity."""

    entry_cost = separate_entry_cost_usdc(position)
    close_size = finite_number(close_quantity)
    open_size = finite_number(open_quantity)
    if entry_cost is None or close_size is None or open_size is None:
        return None
    close_size = abs(close_size)
    open_size = abs(open_size)
    if open_size <= 0 or close_size < 0 or close_size > open_size + 1e-12:
        return None
    return entry_cost * min(1.0, close_size / open_size)


def round_trip_net_pnl_usdc(
    *,
    gross_pnl_usdc: object,
    entry_cost_usdc: object,
    exit_cost_usdc: object,
    funding_cost_usdc: object = 0.0,
) -> float | None:
    """Compute net paper PnL only when every requested component is known."""

    gross = finite_number(gross_pnl_usdc)
    entry = finite_number(entry_cost_usdc)
    exit_cost = finite_number(exit_cost_usdc)
    funding = finite_number(funding_cost_usdc)
    if None in (gross, entry, exit_cost, funding):
        return None
    assert gross is not None
    assert entry is not None
    assert exit_cost is not None
    assert funding is not None
    if entry < 0 or exit_cost < 0:
        return None
    net = gross - entry - exit_cost - funding
    return net if math.isfinite(net) else None


def fee_token_to_pnl_currency_receipt(
    *, fee_amount: object, fee_token: object, pnl_currency: object, token_to_pnl_rate: object | None
) -> dict[str, object]:
    """Convert a fee token explicitly; never add unlike tokens as if they were USD."""
    amount = finite_number(fee_amount)
    if amount is None or amount < 0 or not isinstance(fee_token, str) or not fee_token.strip() or not isinstance(pnl_currency, str) or not pnl_currency.strip():
        return {"status": "UNMEASURABLE", "reason": "FEE_CURRENCY_INPUT_INVALID"}
    if fee_token.strip().upper() == pnl_currency.strip().upper():
        if token_to_pnl_rate is not None and (finite_number(token_to_pnl_rate) is None or float(token_to_pnl_rate) != 1.0):
            return {"status": "UNMEASURABLE", "reason": "IDENTITY_RATE_INVALID"}
        return {"status": "PROVEN", "fee_pnl_currency": amount, "conversion_rate": 1.0, "fee_token": fee_token.strip(), "pnl_currency": pnl_currency.strip()}
    rate = finite_number(token_to_pnl_rate)
    if rate is None or rate < 0:
        return {"status": "UNMEASURABLE", "reason": "CONVERSION_RATE_MISSING"}
    return {"status": "PROVEN", "fee_pnl_currency": round(amount * rate, 10), "conversion_rate": rate, "fee_token": fee_token.strip(), "pnl_currency": pnl_currency.strip()}


@dataclass(frozen=True, slots=True)
class NamedRoiMetrics:
    pnl_usdc: float
    roi_on_initial_capital_pct: float | None
    roi_on_peak_margin_pct: float | None
    roi_on_average_capital_at_risk_pct: float | None
    initial_capital_usdc: float
    peak_margin_usdc: float | None
    average_capital_at_risk_usdc: float | None

    def to_dict(self) -> dict[str, float | None]:
        return asdict(self)


def named_roi_metrics(
    *,
    pnl_usdc: object,
    initial_capital_usdc: object,
    peak_margin_usdc: object | None = None,
    average_capital_at_risk_usdc: object | None = None,
) -> NamedRoiMetrics:
    """Compute only explicitly named ROI denominators.

    A missing or invalid denominator produces ``None``.  In particular,
    ``initial capital - cash`` is never substituted for deployed capital.
    """

    pnl = finite_number(pnl_usdc)
    initial = finite_number(initial_capital_usdc)
    peak = finite_number(peak_margin_usdc)
    average = finite_number(average_capital_at_risk_usdc)
    if pnl is None:
        raise ValueError("pnl_usdc must be finite")
    if initial is None or initial <= 0:
        raise ValueError("initial_capital_usdc must be finite and positive")

    def ratio(denominator: float | None) -> float | None:
        if denominator is None or denominator <= 0:
            return None
        return round(pnl / denominator * 100.0, 10)

    return NamedRoiMetrics(
        pnl_usdc=pnl,
        roi_on_initial_capital_pct=ratio(initial),
        roi_on_peak_margin_pct=ratio(peak),
        roi_on_average_capital_at_risk_pct=ratio(average),
        initial_capital_usdc=initial,
        peak_margin_usdc=peak,
        average_capital_at_risk_usdc=average,
    )


def read_session_starting_equity(state_path: Path) -> float | None:
    """Read the declared session baseline without inventing a default."""

    try:
        payload: Any = json.loads(Path(state_path).read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError, TypeError):
        return None
    if not isinstance(payload, dict):
        return None
    value = finite_number(payload.get("simulation_starting_equity_usdt"))
    return value if value is not None and value > 0 else None


def _accounting_base(status: str, **values: Any) -> dict[str, Any]:
    return {
        "status": status,
        "paper_read_only": True,
        "real_execution": False,
        "promotion": "DISABLED_UNTIL_REVIEW",
        **values,
    }


def _accounting_integer(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _accounting_finite(value: Any) -> bool:
    return finite_number(value) is not None


def accounting_truth_safety_receipt(result: Mapping[str, Any]) -> dict[str, Any]:
    valid = isinstance(result, Mapping) and result.get("paper_read_only") is not False and result.get("real_execution") is not True
    return _accounting_base("PROVEN" if valid else "REJECTED", verdict="ACCOUNTING_TRUTH_SAFE" if valid else "ACCOUNTING_TRUTH_UNSAFE", fail_closed=not valid)


def accounting_required_field_receipt(row: Mapping[str, Any], *, field: str) -> dict[str, Any]:
    valid = isinstance(row, Mapping) and isinstance(field, str) and bool(field) and row.get(field) not in (None, "")
    return _accounting_base("PROVEN" if valid else "REJECTED", verdict="ACCOUNTING_FIELD_PRESENT" if valid else "ACCOUNTING_FIELD_MISSING", field=field, fail_closed=not valid)


def accounting_null_field_receipt(row: Mapping[str, Any], *, field: str) -> dict[str, Any]:
    valid = isinstance(row, Mapping) and isinstance(field, str) and bool(field) and row.get(field) is not None
    return _accounting_base("PROVEN" if valid else "REJECTED", verdict="ACCOUNTING_FIELD_NON_NULL" if valid else "ACCOUNTING_FIELD_NULL", field=field, fail_closed=not valid)


def accounting_field_type_receipt(row: Mapping[str, Any], *, field: str, expected_type: type) -> dict[str, Any]:
    valid = isinstance(row, Mapping) and isinstance(expected_type, type) and isinstance(row.get(field), expected_type)
    return _accounting_base("PROVEN" if valid else "REJECTED", verdict="ACCOUNTING_FIELD_TYPE_VALID" if valid else "ACCOUNTING_FIELD_TYPE_INVALID", field=field, fail_closed=not valid)


def accounting_finite_receipt(value: Any) -> dict[str, Any]:
    valid = _accounting_finite(value)
    return _accounting_base("PROVEN" if valid else "REJECTED", verdict="ACCOUNTING_VALUE_FINITE" if valid else "ACCOUNTING_VALUE_NON_FINITE", value=float(value) if valid else None, fail_closed=not valid)


def accounting_cutoff_receipt(*, event_ts_ms: Any, cutoff_ts_ms: Any) -> dict[str, Any]:
    valid = _accounting_integer(event_ts_ms) and _accounting_integer(cutoff_ts_ms) and event_ts_ms <= cutoff_ts_ms
    return _accounting_base("PROVEN" if valid else "REJECTED", verdict="ACCOUNTING_EVENT_WITHIN_CUTOFF" if valid else "ACCOUNTING_EVENT_AFTER_CUTOFF", fail_closed=not valid)


def accounting_age_receipt(*, event_ts_ms: Any, oldest_allowed_ts_ms: Any) -> dict[str, Any]:
    valid = _accounting_integer(event_ts_ms) and _accounting_integer(oldest_allowed_ts_ms) and event_ts_ms >= oldest_allowed_ts_ms
    return _accounting_base("PROVEN" if valid else "REJECTED", verdict="ACCOUNTING_EVENT_AGE_VALID" if valid else "ACCOUNTING_EVENT_TOO_OLD", fail_closed=not valid)


def accounting_duplicate_receipt(*, event_ids: Sequence[Any]) -> dict[str, Any]:
    valid = bool(event_ids) and all(str(value).strip() for value in event_ids) and len(event_ids) == len(set(event_ids))
    return _accounting_base("PROVEN" if valid else "REJECTED", verdict="ACCOUNTING_EVENTS_UNIQUE" if valid else "ACCOUNTING_EVENT_DUPLICATE_OR_EMPTY", fail_closed=not valid)


def accounting_retry_receipt(*, attempts: Any, max_attempts: Any, checkpoint_saved: bool) -> dict[str, Any]:
    valid = _accounting_integer(attempts) and _accounting_integer(max_attempts) and 1 <= attempts <= max_attempts and checkpoint_saved is True
    return _accounting_base("PROVEN" if valid else "REJECTED", verdict="ACCOUNTING_RETRY_BOUNDED" if valid else "ACCOUNTING_RETRY_UNSAFE", fail_closed=not valid)


def accounting_replay_receipt(*, outputs: Sequence[Any]) -> dict[str, Any]:
    valid = bool(outputs) and len({repr(value) for value in outputs}) == 1
    return _accounting_base("PROVEN" if valid else "REJECTED", verdict="ACCOUNTING_REPLAY_DETERMINISTIC" if valid else "ACCOUNTING_REPLAY_DIVERGED", fail_closed=not valid)


def accounting_fill_duplicate_receipt(*, fill_ids: Sequence[Any]) -> dict[str, Any]:
    valid = bool(fill_ids) and all(str(value).strip() for value in fill_ids) and len(fill_ids) == len(set(fill_ids))
    return _accounting_base("PROVEN" if valid else "REJECTED", verdict="ACCOUNTING_FILLS_UNIQUE" if valid else "ACCOUNTING_FILL_DUPLICATED", fail_closed=not valid)


def accounting_rejection_no_debit_receipt(*, rejected: bool, debited: bool) -> dict[str, Any]:
    valid = rejected is True and debited is False
    return _accounting_base("PROVEN" if valid else "REJECTED", verdict="ACCOUNTING_REJECTION_NO_DEBIT" if valid else "ACCOUNTING_REJECTION_DEBITED", fail_closed=not valid)


def accounting_partial_close_receipt(*, close_quantity: Any, open_quantity: Any, fee_known: bool, fee_amount: Any) -> dict[str, Any]:
    close = finite_number(close_quantity)
    open_size = finite_number(open_quantity)
    fee = finite_number(fee_amount)
    valid = close is not None and open_size is not None and fee is not None and fee_known is True and 0 < close < open_size and fee >= 0
    return _accounting_base("PROVEN" if valid else "REJECTED", verdict="ACCOUNTING_PARTIAL_CLOSE_COSTED" if valid else "ACCOUNTING_PARTIAL_CLOSE_UNSAFE", fail_closed=not valid)


def accounting_total_close_release_receipt(*, close_quantity: Any, open_quantity: Any, released_margin: Any) -> dict[str, Any]:
    close = finite_number(close_quantity)
    open_size = finite_number(open_quantity)
    release = finite_number(released_margin)
    valid = close is not None and open_size is not None and release is not None and open_size > 0 and abs(close - open_size) <= 1e-12 and release >= 0
    return _accounting_base("PROVEN" if valid else "REJECTED", verdict="ACCOUNTING_TOTAL_CLOSE_RELEASED" if valid else "ACCOUNTING_TOTAL_CLOSE_NOT_RELEASED", fail_closed=not valid)


def accounting_mark_liquidability_receipt(*, mark_price: Any, bid: Any, ask: Any) -> dict[str, Any]:
    mark = finite_number(mark_price)
    best_bid = finite_number(bid)
    best_ask = finite_number(ask)
    valid = mark is not None and best_bid is not None and best_ask is not None and best_bid > 0 and best_ask >= best_bid and best_bid <= mark <= best_ask
    return _accounting_base("PROVEN" if valid else "REJECTED", verdict="ACCOUNTING_MARK_LIQUIDABLE" if valid else "ACCOUNTING_MARK_NOT_LIQUIDABLE", fail_closed=not valid)


def accounting_balance_receipt(*, balance: Any) -> dict[str, Any]:
    value = finite_number(balance)
    valid = value is not None and value >= 0
    return _accounting_base("PROVEN" if valid else "REJECTED", verdict="ACCOUNTING_BALANCE_NON_NEGATIVE" if valid else "ACCOUNTING_BALANCE_NEGATIVE", fail_closed=not valid)


def accounting_funding_sign_receipt(*, amount: Any, direction: str) -> dict[str, Any]:
    value = finite_number(amount)
    normalized = str(direction or "").strip().upper()
    valid = value is not None and ((normalized == "CREDIT" and value >= 0) or (normalized == "DEBIT" and value <= 0))
    return _accounting_base("PROVEN" if valid else "REJECTED", verdict="ACCOUNTING_FUNDING_SIGN_VALID" if valid else "ACCOUNTING_FUNDING_SIGN_INVALID", fail_closed=not valid)


def accounting_conversion_receipt(*, fee_amount: Any, fee_token: Any, pnl_currency: Any, token_to_pnl_rate: Any) -> dict[str, Any]:
    result = fee_token_to_pnl_currency_receipt(fee_amount=fee_amount, fee_token=fee_token, pnl_currency=pnl_currency, token_to_pnl_rate=token_to_pnl_rate)
    valid = result.get("status") == "PROVEN"
    return _accounting_base("PROVEN" if valid else "REJECTED", verdict="ACCOUNTING_CONVERSION_PROVEN" if valid else "ACCOUNTING_CONVERSION_MISSING", detail=result, fail_closed=not valid)


def accounting_commit_receipt(*, crashed: bool, committed: bool, checkpoint_saved: bool) -> dict[str, Any]:
    valid = (crashed is True and committed is False and checkpoint_saved is True) or (crashed is False and committed is True)
    return _accounting_base("PROVEN" if valid else "REJECTED", verdict="ACCOUNTING_COMMIT_ATOMIC" if valid else "ACCOUNTING_COMMIT_PARTIAL", fail_closed=not valid)


def accounting_concurrent_write_receipt(*, write_ids: Sequence[Any]) -> dict[str, Any]:
    valid = bool(write_ids) and all(str(value).strip() for value in write_ids) and len(write_ids) == len(set(write_ids))
    return _accounting_base("PROVEN" if valid else "REJECTED", verdict="ACCOUNTING_WRITES_UNIQUE" if valid else "ACCOUNTING_DOUBLE_WRITE", fail_closed=not valid)


__all__ = [
    "ACCOUNTING_SCHEMA_VERSION",
    "NamedRoiMetrics",
    "allocated_entry_cost_usdc",
    "finite_number",
    "first_not_none",
    "named_roi_metrics",
    "read_session_starting_equity",
    "round_trip_net_pnl_usdc",
    "fee_token_to_pnl_currency_receipt",
    "separate_entry_cost_usdc",
    "accounting_truth_safety_receipt",
    "accounting_required_field_receipt",
    "accounting_null_field_receipt",
    "accounting_field_type_receipt",
    "accounting_finite_receipt",
    "accounting_cutoff_receipt",
    "accounting_age_receipt",
    "accounting_duplicate_receipt",
    "accounting_retry_receipt",
    "accounting_replay_receipt",
    "accounting_fill_duplicate_receipt",
    "accounting_rejection_no_debit_receipt",
    "accounting_partial_close_receipt",
    "accounting_total_close_release_receipt",
    "accounting_mark_liquidability_receipt",
    "accounting_balance_receipt",
    "accounting_funding_sign_receipt",
    "accounting_conversion_receipt",
    "accounting_commit_receipt",
    "accounting_concurrent_write_receipt",
]
