"""Read-only execution and launcher controls for the Copy-Vault paper path.

These gates consume caller-provided observations only.  They never call a
venue, create an order, sign a payload, or infer missing market state.
"""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from decimal import Decimal, InvalidOperation
from typing import Any


def _base(status: str, **values: Any) -> dict[str, Any]:
    return {
        "status": status,
        "paper_read_only": True,
        "real_execution": False,
        "promotion": "DISABLED_UNTIL_REVIEW",
        **values,
    }


def _number(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed if math.isfinite(parsed) else None


def maker_style_launcher_receipt(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """Require maker claims to remain simulated and outside execution authority."""
    if not rows:
        return _base("MORE_DATA", reason="empty_maker_launcher_sample")
    invalid: list[int] = []
    for index, row in enumerate(rows):
        if (
            not isinstance(row, Mapping)
            or row.get("execution_style") != "maker"
            or row.get("simulated") is not True
            or row.get("execution_attempted") is True
            or row.get("scope") != "copy-vault"
        ):
            invalid.append(index)
    return _base(
        "PROVEN" if not invalid else "REJECTED",
        verdict="MAKER_STYLE_SIMULATED" if not invalid else "MAKER_STYLE_EXECUTION_PATH_REJECTED",
        rows=len(rows),
        invalid_rows=invalid,
    )


def nonzero_placement_latency_receipt(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """Require an observed positive placement interval, never an imputed zero."""
    if not rows:
        return _base("MORE_DATA", reason="empty_placement_latency_sample")
    invalid: list[int] = []
    latencies: list[float] = []
    for index, row in enumerate(rows):
        sent = _number(row.get("sent_ts_ms")) if isinstance(row, Mapping) else None
        ack = _number(row.get("ack_ts_ms")) if isinstance(row, Mapping) else None
        request_id = str(row.get("request_id") or "").strip() if isinstance(row, Mapping) else ""
        if not request_id or sent is None or ack is None or ack <= sent:
            invalid.append(index)
        else:
            latencies.append(ack - sent)
    return _base(
        "PROVEN" if not invalid else "UNMEASURABLE",
        verdict="NONZERO_PLACEMENT_LATENCY" if not invalid else "PLACEMENT_LATENCY_MISSING_OR_ZERO",
        rows=len(rows),
        invalid_rows=invalid,
        min_latency_ms=min(latencies) if latencies else None,
    )


def positive_liquidity_requires_book_receipt(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """Reject positive liquidity claims that have no point-in-time book."""
    if not rows:
        return _base("MORE_DATA", reason="empty_liquidity_sample")
    invalid: list[int] = []
    for index, row in enumerate(rows):
        liquidity = _number(row.get("liquidity_usd")) if isinstance(row, Mapping) else None
        book_present = row.get("book_present") if isinstance(row, Mapping) else None
        if liquidity is None or liquidity < 0 or not isinstance(book_present, bool):
            invalid.append(index)
        elif liquidity > 0 and not book_present:
            invalid.append(index)
    return _base(
        "PROVEN" if not invalid else "REJECTED",
        verdict="POSITIVE_LIQUIDITY_BOOK_BACKED" if not invalid else "POSITIVE_LIQUIDITY_WITHOUT_BOOK",
        rows=len(rows),
        invalid_rows=invalid,
    )


def partial_fill_then_close_receipt(events: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """Require a causal partial-fill then close sequence for one order."""
    if not events:
        return _base("MORE_DATA", reason="empty_partial_close_sequence")
    if len(events) != 2:
        return _base("UNMEASURABLE", reason="partial_close_sequence_must_have_two_events")
    first, second = events
    if not isinstance(first, Mapping) or not isinstance(second, Mapping):
        return _base("UNMEASURABLE", reason="partial_close_event_invalid")
    valid = (
        first.get("event_type") == "PARTIAL_FILL"
        and second.get("event_type") == "CLOSE"
        and first.get("order_id") == second.get("order_id")
        and _number(first.get("filled_qty")) is not None
        and _number(first.get("filled_qty")) > 0
        and _number(second.get("closed_qty")) is not None
        and _number(second.get("closed_qty")) > 0
        and _number(second.get("ts_ms")) is not None
        and _number(first.get("ts_ms")) is not None
        and _number(second.get("ts_ms")) > _number(first.get("ts_ms"))
        and _number(second.get("closed_qty")) <= _number(first.get("filled_qty"))
    )
    return _base(
        "PROVEN" if valid else "REJECTED",
        verdict="PARTIAL_FILL_THEN_CLOSE" if valid else "PARTIAL_CLOSE_SEQUENCE_INVALID",
        order_id=first.get("order_id"),
    )


def catastrophe_stop_gap_receipt(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """Require a market gap during catastrophe stop to remain fail-closed."""
    if not rows:
        return _base("MORE_DATA", reason="empty_catastrophe_gap_replay")
    invalid: list[int] = []
    gap_count = 0
    for index, row in enumerate(rows):
        gap = row.get("gap_detected") if isinstance(row, Mapping) else None
        if gap is not True:
            invalid.append(index)
            continue
        gap_count += 1
        if row.get("stop_decision") != "VETO_NO_EXECUTION" or row.get("executed") is not False:
            invalid.append(index)
    return _base(
        "PROVEN" if gap_count and not invalid else "REJECTED",
        verdict="CATASTROPHE_GAP_FAIL_CLOSED" if gap_count and not invalid else "CATASTROPHE_GAP_EXECUTION_NOT_VETOED",
        gap_count=gap_count,
        invalid_rows=invalid,
    )


def symbol_min_size_rounding_receipt(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """Verify symbol-specific minimum size and deterministic downward rounding."""
    if not rows:
        return _base("MORE_DATA", reason="empty_symbol_rounding_sample")
    invalid: list[int] = []
    for index, row in enumerate(rows):
        if not isinstance(row, Mapping) or not str(row.get("symbol") or "").strip():
            invalid.append(index)
            continue
        try:
            requested = Decimal(str(row["requested_qty"]))
            minimum = Decimal(str(row["min_qty"]))
            step = Decimal(str(row["step_qty"]))
            rounded = Decimal(str(row["rounded_qty"]))
            expected = (requested // step) * step
        except (KeyError, InvalidOperation, ValueError, ZeroDivisionError):
            invalid.append(index)
            continue
        if requested <= 0 or minimum <= 0 or step <= 0 or rounded != expected or rounded < minimum or rounded > requested:
            invalid.append(index)
    return _base(
        "PROVEN" if not invalid else "REJECTED",
        verdict="SYMBOL_MIN_SIZE_ROUNDING_SAFE" if not invalid else "SYMBOL_SIZE_ROUNDING_INVALID",
        rows=len(rows),
        invalid_rows=invalid,
    )


def funding_on_hold_exposure_receipt(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """Verify funding is computed from held exposure and observed duration."""
    if not rows:
        return _base("MORE_DATA", reason="empty_funding_hold_sample")
    invalid: list[int] = []
    for index, row in enumerate(rows):
        if not isinstance(row, Mapping) or row.get("position_open") is not True:
            invalid.append(index)
            continue
        exposure = _number(row.get("exposure_usd"))
        rate = _number(row.get("funding_bps_8h"))
        hours = _number(row.get("hold_hours"))
        observed = _number(row.get("funding_usd"))
        if exposure is None or rate is None or hours is None or observed is None or exposure <= 0 or hours <= 0:
            invalid.append(index)
            continue
        expected = exposure * rate / 10_000.0 * hours / 8.0
        if not math.isclose(observed, expected, rel_tol=1e-9, abs_tol=1e-9):
            invalid.append(index)
    return _base(
        "PROVEN" if not invalid else "REJECTED",
        verdict="FUNDING_CHARGED_ON_HELD_EXPOSURE" if not invalid else "FUNDING_EXPOSURE_MISMATCH",
        rows=len(rows),
        invalid_rows=invalid,
    )


def leader_takeover_vs_stop_receipt(events: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """Require a catastrophe stop to veto a competing leader takeover."""
    if not events:
        return _base("MORE_DATA", reason="empty_takeover_stop_sequence")
    stops = [event for event in events if isinstance(event, Mapping) and event.get("source") == "STOP"]
    takeovers = [event for event in events if isinstance(event, Mapping) and event.get("source") == "LEADER_TAKEOVER"]
    valid = bool(stops and takeovers)
    if valid:
        stop = min(stops, key=lambda event: _number(event.get("ts_ms")) or math.inf)
        takeover = min(takeovers, key=lambda event: _number(event.get("ts_ms")) or math.inf)
        valid = (
            _number(stop.get("ts_ms")) is not None
            and _number(takeover.get("ts_ms")) is not None
            and _number(stop.get("ts_ms")) <= _number(takeover.get("ts_ms"))
            and stop.get("decision") == "VETO_NO_EXECUTION"
            and takeover.get("executed") is False
        )
    return _base(
        "PROVEN" if valid else "REJECTED",
        verdict="STOP_OVERRIDES_LEADER_TAKEOVER" if valid else "LEADER_TAKEOVER_NOT_VETOED",
        stop_count=len(stops),
        takeover_count=len(takeovers),
    )


def position_inversion_two_trades_receipt(events: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """Require an inversion to be represented by close-then-open, never one opaque trade."""
    if len(events) != 2:
        return _base("UNMEASURABLE", reason="position_inversion_requires_two_trades")
    first, second = events
    valid = (
        all(isinstance(event, Mapping) for event in events)
        and first.get("trade_type") == "CLOSE"
        and second.get("trade_type") == "OPEN"
        and first.get("symbol") == second.get("symbol")
        and _number(first.get("ts_ms")) is not None
        and _number(second.get("ts_ms")) is not None
        and _number(second.get("ts_ms")) > _number(first.get("ts_ms"))
        and _number(first.get("qty")) is not None
        and _number(second.get("qty")) is not None
        and _number(first.get("qty")) > 0
        and _number(second.get("qty")) > 0
    )
    return _base(
        "PROVEN" if valid else "REJECTED",
        verdict="POSITION_INVERSION_TWO_TRADES" if valid else "POSITION_INVERSION_SEQUENCE_INVALID",
        symbol=first.get("symbol") if isinstance(first, Mapping) else None,
    )


def client_network_no_order_receipt(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """Prove the client layer exposes no order-capable network path."""
    if not rows:
        return _base("MORE_DATA", reason="empty_client_network_audit")
    invalid: list[int] = []
    forbidden = ("order", "execute", "trade", "sign")
    for index, row in enumerate(rows):
        endpoint = str(row.get("endpoint") or "").lower() if isinstance(row, Mapping) else ""
        if (
            not endpoint
            or any(token in endpoint for token in forbidden)
            or row.get("read_only") is not True
            or row.get("signed") is not False
            or row.get("real_execution") is not False
            or row.get("network_action") not in {"GET", "SUBSCRIBE"}
        ):
            invalid.append(index)
    return _base(
        "PROVEN" if not invalid else "REJECTED",
        verdict="CLIENT_NETWORK_NO_ORDER_PATH" if not invalid else "CLIENT_NETWORK_ORDER_PATH_REJECTED",
        rows=len(rows),
        invalid_rows=invalid,
    )


__all__ = [
    "maker_style_launcher_receipt",
    "nonzero_placement_latency_receipt",
    "positive_liquidity_requires_book_receipt",
    "partial_fill_then_close_receipt",
    "catastrophe_stop_gap_receipt",
    "symbol_min_size_rounding_receipt",
    "funding_on_hold_exposure_receipt",
    "leader_takeover_vs_stop_receipt",
    "position_inversion_two_trades_receipt",
    "client_network_no_order_receipt",
]
