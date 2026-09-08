"""Conservative TRAIN-only maker fill measurement for Lead-Lag research.

A touch or a visible L2 depletion is never sufficient to claim a maker fill.
The simulated order is placed behind the full observable top-level queue and
advances only on signed aggressive trades at that exact price after the order
became observable.  Cancellations therefore cannot manufacture fills.

Pure research helper: no network, no orders, PAPER/READ-ONLY only.
"""
from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from typing import Any

from hl_observer.backtesting.queue_model import avancer

QUEUE_MODEL = "RISK_AVERSE_SIGNED_TRADE_FLOW"


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
    executed at that bid.  SELL mirrors this at the best ask with BUY-aggressor
    flow.  All events at/before ``observable_at_ms`` are excluded from queue
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
    state_qty = float(queue_ahead_qty)
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
            "order_qty": float(notional) / float(limit_price),
            "aggressive_qty_at_level": float(aggressive_qty),
            "remaining_queue_ahead_qty": float(state_qty),
            "fill_ts_ms": fill_ts_ms,
        }
    )
    return result


__all__ = ["QUEUE_MODEL", "evaluate_measured_maker_queue_fill"]
