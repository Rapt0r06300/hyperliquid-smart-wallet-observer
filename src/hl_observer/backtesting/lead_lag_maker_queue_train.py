"""Conservative TRAIN-only maker measurement for Lead-Lag research.

A touch or a visible L2 depletion is never sufficient to claim a maker fill.
The simulated order is placed behind the full observable top-level queue and
advances only on signed aggressive trades at that exact price after the order
became observable. Cancellations therefore cannot manufacture fills.

The same surface also loads the canonical recorded Hyperliquid public-trade
tape through physically clamped TRAIN windows. No validation/OOS/forward row
is intentionally read by this research helper.
"""
from __future__ import annotations

import math
from collections import defaultdict
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from hl_observer.backtesting.queue_model import avancer
from hl_observer.simulation.lead_lag_l2_history import load_market_microstructure_history

QUEUE_MODEL = "RISK_AVERSE_SIGNED_TRADE_FLOW_FULL_ORDER_V2"
TRAIN_TAPE_SCHEMA_VERSION = "hypersmart.lead_lag_maker_train_data.v1"


def _finite_positive(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    if not math.isfinite(number) or number <= 0.0:
        return None
    return number


def _base_result(*, status: str, filled: bool, reason: str | None = None) -> dict[str, Any]:
    return {
        "status": status,
        "filled": bool(filled),
        "reason": reason,
        "queue_model": QUEUE_MODEL,
        "selection_scope": "TRAIN_ONLY_PRE_FREEZE",
        "paper_read_only": True,
        "real_execution": False,
    }


def evaluate_measured_maker_queue_fill(
    books: Sequence[Mapping[str, Any]],
    aggressive_trades: Sequence[Mapping[str, Any]],
    *,
    side: str,
    observable_at_ms: int,
    deadline_ms: int,
    notional_usd: float,
) -> dict[str, Any]:
    """Measure one conservative maker fill from causally observable tape.

    BUY joins the recorded best bid and can advance only on SELL-aggressor flow
    executed at that bid. SELL mirrors this at the best ask with BUY-aggressor
    flow. All events at/before ``observable_at_ms`` are excluded from queue
    consumption, preventing pre-order flow from leaking into the result.
    """

    selected_side = str(side).strip().upper()
    if selected_side not in {"BUY", "SELL"}:
        return _base_result(status="MAKER_FILL_UNMEASURABLE", filled=False, reason="INVALID_SIDE")
    if int(deadline_ms) < int(observable_at_ms):
        return _base_result(status="MAKER_FILL_UNMEASURABLE", filled=False, reason="INVALID_WINDOW")
    notional = _finite_positive(notional_usd)
    if notional is None:
        return _base_result(status="MAKER_FILL_UNMEASURABLE", filled=False, reason="INVALID_NOTIONAL")

    observable_books: list[Mapping[str, Any]] = []
    for row in books:
        try:
            timestamp_ms = int(row.get("ts_ms"))
        except (TypeError, ValueError, OverflowError):
            continue
        if int(observable_at_ms) <= timestamp_ms <= int(deadline_ms):
            observable_books.append(row)
    observable_books.sort(key=lambda row: int(row.get("ts_ms") or 0))
    if not observable_books:
        return _base_result(status="MAKER_FILL_UNMEASURABLE", filled=False, reason="NO_OBSERVABLE_BOOK")

    initial = observable_books[0]
    price_key = "bid" if selected_side == "BUY" else "ask"
    size_key = "bid_size" if selected_side == "BUY" else "ask_size"
    limit_price = _finite_positive(initial.get(price_key))
    queue_ahead_qty = _finite_positive(initial.get(size_key))
    if limit_price is None:
        return _base_result(status="MAKER_FILL_UNMEASURABLE", filled=False, reason="MISSING_LIMIT_PRICE")
    if queue_ahead_qty is None:
        return _base_result(status="MAKER_FILL_UNMEASURABLE", filled=False, reason="MISSING_QUEUE_DEPTH")

    required_aggressor = "SELL" if selected_side == "BUY" else "BUY"
    order_qty = float(notional) / float(limit_price)
    state_qty = float(queue_ahead_qty) + order_qty
    filled = False
    fill_ts_ms: int | None = None
    aggressive_qty = 0.0

    ordered_trades: list[tuple[int, float]] = []
    for row in aggressive_trades:
        try:
            timestamp_ms = int(row.get("ts_ms"))
        except (TypeError, ValueError, OverflowError):
            continue
        if not (int(observable_at_ms) < timestamp_ms <= int(deadline_ms)):
            continue
        if str(row.get("aggressor_side") or "").strip().upper() != required_aggressor:
            continue
        trade_price = _finite_positive(row.get("price"))
        quantity = _finite_positive(row.get("qty"))
        if trade_price is None or quantity is None:
            continue
        if not math.isclose(trade_price, limit_price, rel_tol=1e-12, abs_tol=1e-12):
            continue
        ordered_trades.append((timestamp_ms, quantity))
    ordered_trades.sort(key=lambda item: item[0])

    for timestamp_ms, quantity in ordered_trades:
        aggressive_qty += quantity
        state = avancer(state_qty, chg_carnet=0.0, qty_trade=quantity)
        state_qty = state.qty_devant
        if state.rempli:
            filled = True
            fill_ts_ms = int(timestamp_ms)
            break

    result = _base_result(
        status="FILLED_MEASURED_QUEUE" if filled else "NOT_FILLED_MEASURED_QUEUE",
        filled=filled,
    )
    result.update(
        {
            "side": selected_side,
            "observable_at_ms": int(observable_at_ms),
            "deadline_ms": int(deadline_ms),
            "limit_price": float(limit_price),
            "queue_ahead_qty": float(queue_ahead_qty),
            "queue_ahead_usd": float(queue_ahead_qty) * float(limit_price),
            "order_qty": order_qty,
            "aggressive_qty_at_level": float(aggressive_qty),
            "remaining_queue_ahead_qty": max(
                0.0, float(queue_ahead_qty) - float(aggressive_qty)
            ),
            "remaining_order_qty": float(state_qty),
            "fill_ts_ms": fill_ts_ms,
        }
    )
    return result


def _normalized_ranges(train_ranges: Sequence[Sequence[int]]) -> list[tuple[int, int]]:
    ranges: list[tuple[int, int]] = []
    for raw in train_ranges:
        if len(raw) < 2:
            continue
        try:
            start_ms = int(raw[0])
            end_ms = int(raw[1])
        except (TypeError, ValueError, OverflowError):
            continue
        if start_ms <= 0 or end_ms < start_ms:
            continue
        ranges.append((start_ms, end_ms))
    ranges.sort()
    merged: list[tuple[int, int]] = []
    for start_ms, end_ms in ranges:
        if not merged or start_ms > merged[-1][1] + 1:
            merged.append((start_ms, end_ms))
            continue
        merged[-1] = (merged[-1][0], max(merged[-1][1], end_ms))
    return merged


def _contains(timestamp_ms: int, ranges: Sequence[tuple[int, int]]) -> bool:
    return any(start_ms <= timestamp_ms <= end_ms for start_ms, end_ms in ranges)


def _clipped_event_windows(
    event_ts_ms: Sequence[int],
    train_ranges: Sequence[tuple[int, int]],
    *,
    before_ms: int,
    after_ms: int,
) -> tuple[list[tuple[int, int]], int]:
    windows: list[tuple[int, int]] = []
    events_rejected = 0
    before = max(0, int(before_ms))
    after = max(0, int(after_ms))
    for raw_timestamp in event_ts_ms:
        try:
            timestamp_ms = int(raw_timestamp)
        except (TypeError, ValueError, OverflowError):
            events_rejected += 1
            continue
        containing = next(
            ((start_ms, end_ms) for start_ms, end_ms in train_ranges if start_ms <= timestamp_ms <= end_ms),
            None,
        )
        if containing is None:
            events_rejected += 1
            continue
        train_start, train_end = containing
        windows.append(
            (
                max(train_start, timestamp_ms - before),
                min(train_end, timestamp_ms + after),
            )
        )

    windows.sort()
    merged: list[tuple[int, int]] = []
    for start_ms, end_ms in windows:
        if not merged or start_ms > merged[-1][1] + 1:
            merged.append((start_ms, end_ms))
            continue
        merged[-1] = (merged[-1][0], max(merged[-1][1], end_ms))
    return merged, events_rejected


def _safe_recorded_trade(row: Mapping[str, Any]) -> bool:
    try:
        timestamp_ms = int(row.get("ts_ms") or 0)
    except (TypeError, ValueError, OverflowError):
        return False
    return bool(
        timestamp_ms > 0
        and str(row.get("coin") or "").strip()
        and str(row.get("side") or "").upper() in {"A", "B"}
        and _finite_positive(row.get("px")) is not None
        and _finite_positive(row.get("sz")) is not None
        and str(row.get("trade_id") or "").strip()
        and str(row.get("source") or "") == "hyperliquid:recorded:trades"
        and str(row.get("data_origin") or "") == "RECORDED_REAL"
        and row.get("read_only") is True
        and row.get("real_execution") is False
    )


def load_train_public_trade_history(
    root: str | Path,
    event_ts_ms: Sequence[int],
    *,
    train_ranges: Sequence[Sequence[int]],
    before_ms: int = 1_000,
    after_ms: int = 17_000,
) -> tuple[dict[str, list[dict[str, Any]]], dict[str, Any]]:
    """Load signed Hyperliquid public trades without reading beyond TRAIN."""

    normalized_ranges = _normalized_ranges(train_ranges)
    windows, events_rejected = _clipped_event_windows(
        event_ts_ms,
        normalized_ranges,
        before_ms=before_ms,
        after_ms=after_ms,
    )
    result: dict[str, list[dict[str, Any]]] = defaultdict(list)
    seen: set[tuple[str, str]] = set()
    duplicates = invalid_or_unsafe = outside_train = 0
    unverified_source_windows = 0
    source_rows_seen = 0
    source_metadata: list[dict[str, Any]] = []

    for start_ms, end_ms in windows:
        _books, trades, meta = load_market_microstructure_history(
            root,
            start_ms=start_ms,
            end_ms=end_ms,
        )
        meta_dict = dict(meta or {})
        source_metadata.append(meta_dict)
        if meta_dict.get("source_time_filter_applied") is not True or meta_dict.get("real_execution") is not False:
            unverified_source_windows += 1
            continue
        for raw_rows in trades.values():
            for raw_row in raw_rows:
                source_rows_seen += 1
                if not isinstance(raw_row, Mapping) or not _safe_recorded_trade(raw_row):
                    invalid_or_unsafe += 1
                    continue
                row = dict(raw_row)
                timestamp_ms = int(row["ts_ms"])
                if timestamp_ms < start_ms or timestamp_ms > end_ms or not _contains(timestamp_ms, normalized_ranges):
                    outside_train += 1
                    continue
                coin = str(row["coin"]).upper()
                identity = (coin, str(row["trade_id"]))
                if identity in seen:
                    duplicates += 1
                    continue
                seen.add(identity)
                result[coin].append(row)

    finalized = dict(result)
    for rows in finalized.values():
        rows.sort(key=lambda row: (int(row["ts_ms"]), str(row["trade_id"])))

    return finalized, {
        "schema_version": TRAIN_TAPE_SCHEMA_VERSION,
        "selection_scope": "TRAIN_ONLY_PRE_FREEZE",
        "train_ranges": [list(item) for item in normalized_ranges],
        "source_windows": [list(item) for item in windows],
        "events_rejected_outside_train": events_rejected,
        "source_rows_seen": source_rows_seen,
        "trade_rows": sum(len(rows) for rows in finalized.values()),
        "coins_with_trades": sorted(finalized),
        "duplicate_trades_rejected": duplicates,
        "invalid_or_unsafe_trades_rejected": invalid_or_unsafe,
        "rows_rejected_outside_train": outside_train,
        "unverified_source_windows_rejected": unverified_source_windows,
        "source_time_filter_verified": unverified_source_windows == 0,
        "source_metadata": source_metadata,
        "heldout_loaded": False,
        "paper_read_only": True,
        "real_execution": False,
    }


__all__ = [
    "QUEUE_MODEL",
    "TRAIN_TAPE_SCHEMA_VERSION",
    "evaluate_measured_maker_queue_fill",
    "load_train_public_trade_history",
]
