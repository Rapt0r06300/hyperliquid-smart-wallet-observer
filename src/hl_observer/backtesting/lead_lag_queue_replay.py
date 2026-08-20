"""Causal queue-aware maker replay for the Lead-Lag V3 hypothesis.

The mechanism is deliberately narrow and predeclared: a strong rolling ETH
shock observed on Binance may post one passive Hyperliquid order.  A touch is
never a fill.  Recorded public trades must consume both the quantity already
ahead and the complete paper order before the entry exists.  The position is
then closed at a recorded marketable top-of-book price.

This module is local PAPER/READ-ONLY research code.  It has no exchange client
and no order-placement surface.
"""
from __future__ import annotations

import bisect
import hashlib
import json
import math
from collections.abc import Mapping, Sequence
from typing import Any

from hl_observer.fees.hyperliquid_fees import nos_frais

SCHEMA_VERSION = "hypersmart.lead_lag_queue_replay.v1"
REQUIRED_COIN = "ETH"
SHOCK_WINDOW_MS = 1_000
SHOCK_THRESHOLD_BPS = 20.0
SHOCK_COOLDOWN_MS = 5_000
MAKER_LIFETIME_MS = 2_000
HOLD_MS = 5_000
NOTIONAL_USD = 25.0
MAX_BOOK_DELAY_MS = 750
DIAGNOSTIC_LATENCY_MS = 750.0


def _number(value: object) -> float | None:
    try:
        result = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return result if math.isfinite(result) else None


def _stable_id(payload: Mapping[str, Any]) -> str:
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def detect_rolling_shocks(
    trades: Sequence[Sequence[float]],
    *,
    window_ms: int = SHOCK_WINDOW_MS,
    threshold_bps: float = SHOCK_THRESHOLD_BPS,
    cooldown_ms: int = SHOCK_COOLDOWN_MS,
) -> list[dict[str, Any]]:
    """Detect causal rolling-price shocks without consulting future trades."""

    clean: list[tuple[int, float]] = []
    for row in trades:
        if len(row) < 2:
            continue
        timestamp_ns = _number(row[0])
        price = _number(row[1])
        if timestamp_ns is None or price is None or timestamp_ns <= 0 or price <= 0:
            continue
        clean.append((int(timestamp_ns), float(price)))
    clean.sort()

    result: list[dict[str, Any]] = []
    left = 0
    last_trigger_ms = -10**18
    window_ns = max(1, int(window_ms)) * 1_000_000
    for index, (timestamp_ns, price) in enumerate(clean):
        while left < index and timestamp_ns - clean[left][0] > window_ns:
            left += 1
        if left >= index:
            continue
        base_timestamp_ns, base_price = clean[left]
        shock_bps = (price - base_price) / base_price * 10_000.0
        trigger_ms = timestamp_ns // 1_000_000
        if abs(shock_bps) < float(threshold_bps):
            continue
        if trigger_ms - last_trigger_ms < max(0, int(cooldown_ms)):
            continue
        result.append(
            {
                "trigger_ts_ms": int(trigger_ms),
                "window_start_ts_ms": int(base_timestamp_ns // 1_000_000),
                "lead_start_price": float(base_price),
                "lead_trigger_price": float(price),
                "lead_shock_bps": float(shock_bps),
                "direction": 1 if shock_bps > 0 else -1,
            }
        )
        last_trigger_ms = trigger_ms
    return result


def _first_book_at_or_after(
    books: Sequence[Mapping[str, Any]],
    timestamps: Sequence[int],
    target_ms: float,
    *,
    max_delay_ms: int,
) -> Mapping[str, Any] | None:
    index = bisect.bisect_left(timestamps, int(math.ceil(target_ms)))
    if index >= len(books):
        return None
    row = books[index]
    delay = int(row.get("ts_ms") or 0) - float(target_ms)
    if delay < 0 or delay > max(0, int(max_delay_ms)):
        return None
    return row


def _matching_public_trades(
    trades: Sequence[Mapping[str, Any]],
    timestamps: Sequence[int],
    *,
    start_ms: int,
    end_ms: int,
    price: float,
    passive_direction: int,
    earliest_exchange_ms: int | None,
) -> list[Mapping[str, Any]]:
    expected_side = "A" if passive_direction > 0 else "B"
    index = bisect.bisect_right(timestamps, int(start_ms))
    result: list[Mapping[str, Any]] = []
    while index < len(trades):
        row = trades[index]
        observed_ms = int(row.get("ts_ms") or 0)
        if observed_ms > int(end_ms):
            break
        trade_price = _number(row.get("px"))
        exchange_ms = _number(row.get("exchange_ts_ms"))
        if (
            str(row.get("side") or "").upper() == expected_side
            and trade_price is not None
            and math.isclose(trade_price, float(price), rel_tol=1e-10, abs_tol=1e-10)
            and (
                earliest_exchange_ms is None
                or exchange_ms is None
                or exchange_ms >= earliest_exchange_ms
            )
        ):
            result.append(row)
        index += 1
    return result


def _economic_row(
    *,
    shock: Mapping[str, Any],
    direction: int,
    entry_book: Mapping[str, Any],
    fill_trade: Mapping[str, Any],
    exit_book: Mapping[str, Any],
    queue_events: list[dict[str, float]],
    initial_qty_ahead: float,
    paper_order_qty: float,
    notional_usd: float,
    latency_ms: float,
    latency_measured: bool,
    all_queue_events_quality_ready: bool,
    placebo: bool,
) -> dict[str, Any]:
    entry_price = float(entry_book["bid"] if direction > 0 else entry_book["ask"])
    exit_price = float(exit_book["bid"] if direction > 0 else exit_book["ask"])
    entry_mid = 0.5 * (float(entry_book["bid"]) + float(entry_book["ask"]))
    exit_mid = 0.5 * (float(exit_book["bid"]) + float(exit_book["ask"]))
    quantity = float(paper_order_qty)
    entry_notional = quantity * entry_price
    exit_notional = quantity * exit_price
    gross_pnl = float(direction) * (exit_mid - entry_mid) * quantity
    executable_before_fees = float(direction) * (exit_price - entry_price) * quantity
    spread_cost = gross_pnl - executable_before_fees
    fees = nos_frais("perp")
    entry_fee = entry_notional * float(fees.maker_bps) / 10_000.0
    exit_fee = exit_notional * float(fees.taker_bps) / 10_000.0
    fee_cost = entry_fee + exit_fee
    slippage_cost = 0.0
    latency_cost = 0.0  # The delayed entry observation already embeds latency.
    net = executable_before_fees - fee_cost
    exit_capacity_value = (
        exit_book.get("bid_top_usd")
        if direction > 0
        else exit_book.get("ask_top_usd")
    )
    exit_capacity = float(exit_capacity_value or 0.0)
    capacity_ok = exit_capacity + 1e-12 >= exit_notional
    quality_ready = bool(
        entry_book.get("data_gate_ready") is True
        and exit_book.get("data_gate_ready") is True
        and all_queue_events_quality_ready
    )
    reconciliation_ok = math.isclose(
        gross_pnl - fee_cost - spread_cost - slippage_cost - latency_cost,
        net,
        abs_tol=1e-9,
    )
    liquidatable = bool(
        latency_measured and quality_ready and capacity_ok and reconciliation_ok
    )
    identity_payload = {
        "coin": REQUIRED_COIN,
        "trigger_ts_ms": int(shock["trigger_ts_ms"]),
        "direction": int(direction),
        "entry_ts_ms": int(entry_book["ts_ms"]),
        "fill_ts_ms": int(fill_trade["ts_ms"]),
        "exit_ts_ms": int(exit_book["ts_ms"]),
        "placebo": bool(placebo),
    }
    return {
        "trade_id": _stable_id(identity_payload),
        "coin": REQUIRED_COIN,
        "direction": int(direction),
        "side": "LONG" if direction > 0 else "SHORT",
        "lead_shock_bps": float(shock["lead_shock_bps"]),
        "trigger_ts_ms": int(shock["trigger_ts_ms"]),
        "entry_ts_ms": int(entry_book["ts_ms"]),
        "fill_ts_ms": int(fill_trade["ts_ms"]),
        "exit_ts_ms": int(exit_book["ts_ms"]),
        "entry_price": entry_price,
        "exit_price": exit_price,
        "entry_mid": entry_mid,
        "exit_mid": exit_mid,
        "initial_qty_ahead": float(initial_qty_ahead),
        "paper_order_qty": quantity,
        "required_qty_for_full_fill": float(initial_qty_ahead + quantity),
        "queue_events": queue_events,
        "queue_traded_qty": sum(event["traded_qty_at_level"] for event in queue_events),
        "notional_usd": float(notional_usd),
        "entry_notional_usd": entry_notional,
        "exit_notional_usd": exit_notional,
        "exit_top_capacity_usd": exit_capacity,
        "capacity_ok": capacity_ok,
        "maker_entry_fee_bps": float(fees.maker_bps),
        "taker_exit_fee_bps": float(fees.taker_bps),
        "gross_pnl_usd": gross_pnl,
        "fees_usd": fee_cost,
        "spread_cost_usd": spread_cost,
        "slippage_cost_usd": slippage_cost,
        "latency_cost_usd": latency_cost,
        "rebate_usd": 0.0,
        "net_pnl_usd": net,
        "economic_reconciliation_ok": reconciliation_ok,
        "latency_ms": float(latency_ms),
        "latency_measured": bool(latency_measured),
        "latency_embedded_in_delayed_entry": True,
        "data_gate_ready": quality_ready,
        "full_fill": True,
        "closed_position": True,
        "liquidatable_net": liquidatable,
        "LIQUIDATABLE_NET": liquidatable,
        "placebo": bool(placebo),
        "paper_read_only": True,
        "real_execution": False,
        "walk_forward_segment": str(shock.get("walk_forward_segment") or ""),
        "segment": str(shock.get("walk_forward_segment") or ""),
    }


def _replay_one(
    shock: Mapping[str, Any],
    *,
    direction: int,
    books: Sequence[Mapping[str, Any]],
    book_timestamps: Sequence[int],
    public_trades: Sequence[Mapping[str, Any]],
    trade_timestamps: Sequence[int],
    latency_ms: float,
    latency_measured: bool,
    maker_lifetime_ms: int,
    hold_ms: int,
    notional_usd: float,
    max_book_delay_ms: int,
    placebo: bool,
) -> tuple[dict[str, Any] | None, str]:
    target_ms = int(shock["trigger_ts_ms"]) + float(latency_ms)
    entry_book = _first_book_at_or_after(
        books,
        book_timestamps,
        target_ms,
        max_delay_ms=max_book_delay_ms,
    )
    if entry_book is None:
        return None, "MISSING_CAUSAL_ENTRY_BOOK"
    entry_price = float(entry_book["bid"] if direction > 0 else entry_book["ask"])
    initial_ahead = float(entry_book["bid_size"] if direction > 0 else entry_book["ask_size"])
    if entry_price <= 0 or initial_ahead <= 0:
        return None, "INVALID_ENTRY_LEVEL"
    own_quantity = float(notional_usd) / entry_price
    required_quantity = initial_ahead + own_quantity
    earliest_exchange = _number(entry_book.get("exchange_ts_ms"))
    matching = _matching_public_trades(
        public_trades,
        trade_timestamps,
        start_ms=int(entry_book["ts_ms"]),
        end_ms=int(entry_book["ts_ms"]) + int(maker_lifetime_ms),
        price=entry_price,
        passive_direction=direction,
        earliest_exchange_ms=int(earliest_exchange) if earliest_exchange is not None else None,
    )
    queue_events: list[dict[str, float]] = []
    cumulative = 0.0
    fill_trade: Mapping[str, Any] | None = None
    quality_ready = True
    for trade in matching:
        traded_quantity = max(0.0, float(trade.get("sz") or 0.0))
        if traded_quantity <= 0:
            continue
        queue_events.append(
            {"book_size_change": 0.0, "traded_qty_at_level": traded_quantity}
        )
        cumulative += traded_quantity
        quality_ready = quality_ready and trade.get("data_gate_ready") is True
        if cumulative + 1e-12 >= required_quantity:
            fill_trade = trade
            break
    if fill_trade is None:
        return None, "QUEUE_NOT_FULLY_CONSUMED"

    exit_target_ms = int(fill_trade["ts_ms"]) + int(hold_ms)
    exit_book = _first_book_at_or_after(
        books,
        book_timestamps,
        exit_target_ms,
        max_delay_ms=max_book_delay_ms,
    )
    if exit_book is None:
        return None, "MISSING_CAUSAL_EXIT_BOOK"
    return (
        _economic_row(
            shock=shock,
            direction=direction,
            entry_book=entry_book,
            fill_trade=fill_trade,
            exit_book=exit_book,
            queue_events=queue_events,
            initial_qty_ahead=initial_ahead,
            paper_order_qty=own_quantity,
            notional_usd=notional_usd,
            latency_ms=latency_ms,
            latency_measured=latency_measured,
            all_queue_events_quality_ready=quality_ready,
            placebo=placebo,
        ),
        "FILLED_AND_CLOSED",
    )


def _assign_shock_segments(shocks: list[dict[str, Any]]) -> None:
    """Freeze chronological segments before knowing which orders fill."""

    shocks.sort(key=lambda row: int(row["trigger_ts_ms"]))
    count = len(shocks)
    train_end = int(count * 0.60)
    validation_end = int(count * 0.80)
    for index, row in enumerate(shocks):
        if index < train_end:
            segment = "train"
        elif index < validation_end:
            segment = "validation"
        else:
            segment = "oos"
        row["walk_forward_segment"] = segment


def _summary(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    nets = [float(row.get("net_pnl_usd") or 0.0) for row in rows]
    wins = sum(value for value in nets if value > 0)
    losses = -sum(value for value in nets if value < 0)
    return {
        "sample_count": len(rows),
        "net_pnl_usd": round(sum(nets), 8),
        "profit_factor": (
            float("inf") if wins > 0 and losses <= 1e-12 else (wins / losses if losses > 0 else None)
        ),
        "liquidatable_count": sum(row.get("LIQUIDATABLE_NET") is True for row in rows),
        "closed_positions": sum(row.get("closed_position") is True for row in rows),
    }


def replay_lead_lag_queue_maker(
    tape: Mapping[str, Mapping[str, list]],
    l2_history: Mapping[str, Sequence[Mapping[str, Any]]],
    public_trade_history: Mapping[str, Sequence[Mapping[str, Any]]],
    *,
    latency_evidence: Mapping[str, Any],
    coin: str = REQUIRED_COIN,
    shock_window_ms: int = SHOCK_WINDOW_MS,
    shock_threshold_bps: float = SHOCK_THRESHOLD_BPS,
    shock_cooldown_ms: int = SHOCK_COOLDOWN_MS,
    maker_lifetime_ms: int = MAKER_LIFETIME_MS,
    hold_ms: int = HOLD_MS,
    notional_usd: float = NOTIONAL_USD,
    max_book_delay_ms: int = MAX_BOOK_DELAY_MS,
) -> dict[str, Any]:
    """Replay the immutable maker hypothesis and its same-time placebo."""

    selected_coin = str(coin).upper()
    if selected_coin != REQUIRED_COIN:
        raise ValueError(f"predeclared Lead-Lag V3 coin is {REQUIRED_COIN}, got {selected_coin}")
    streams = tape.get(selected_coin) or {}
    lead_trades = list(streams.get("TRADE") or [])
    shocks = detect_rolling_shocks(
        lead_trades,
        window_ms=shock_window_ms,
        threshold_bps=shock_threshold_bps,
        cooldown_ms=shock_cooldown_ms,
    )
    _assign_shock_segments(shocks)
    books = sorted(
        [dict(row) for row in l2_history.get(selected_coin, ())],
        key=lambda row: int(row.get("ts_ms") or 0),
    )
    public_trades = sorted(
        [dict(row) for row in public_trade_history.get(selected_coin, ())],
        key=lambda row: int(row.get("ts_ms") or 0),
    )
    book_timestamps = [int(row.get("ts_ms") or 0) for row in books]
    trade_timestamps = [int(row.get("ts_ms") or 0) for row in public_trades]
    measured = latency_evidence.get("measured") is True
    measured_p95 = _number(latency_evidence.get("p95_ms"))
    applied_latency = float(measured_p95 if measured_p95 is not None else DIAGNOSTIC_LATENCY_MS)

    rows: list[dict[str, Any]] = []
    placebo_rows: list[dict[str, Any]] = []
    diagnostics: dict[str, int] = {}
    for shock in shocks:
        direction = int(shock["direction"])
        row, reason = _replay_one(
            shock,
            direction=direction,
            books=books,
            book_timestamps=book_timestamps,
            public_trades=public_trades,
            trade_timestamps=trade_timestamps,
            latency_ms=applied_latency,
            latency_measured=measured,
            maker_lifetime_ms=maker_lifetime_ms,
            hold_ms=hold_ms,
            notional_usd=notional_usd,
            max_book_delay_ms=max_book_delay_ms,
            placebo=False,
        )
        diagnostics[reason] = diagnostics.get(reason, 0) + 1
        if row is not None:
            rows.append(row)
        placebo, placebo_reason = _replay_one(
            shock,
            direction=-direction,
            books=books,
            book_timestamps=book_timestamps,
            public_trades=public_trades,
            trade_timestamps=trade_timestamps,
            latency_ms=applied_latency,
            latency_measured=measured,
            maker_lifetime_ms=maker_lifetime_ms,
            hold_ms=hold_ms,
            notional_usd=notional_usd,
            max_book_delay_ms=max_book_delay_ms,
            placebo=True,
        )
        diagnostics[f"PLACEBO_{placebo_reason}"] = diagnostics.get(
            f"PLACEBO_{placebo_reason}", 0
        ) + 1
        if placebo is not None:
            placebo_rows.append(placebo)

    rows.sort(key=lambda row: (int(row["trigger_ts_ms"]), str(row["trade_id"])))
    placebo_rows.sort(
        key=lambda row: (int(row["trigger_ts_ms"]), str(row["trade_id"]))
    )
    segment_summaries = {
        segment: _summary(
            [row for row in rows if row.get("walk_forward_segment") == segment]
        )
        for segment in ("train", "validation", "oos")
    }
    placebo_summaries = {
        segment: _summary(
            [row for row in placebo_rows if row.get("walk_forward_segment") == segment]
        )
        for segment in ("train", "validation", "oos")
    }
    return {
        "schema_version": SCHEMA_VERSION,
        "mechanism": "lead_lag_v3_eth_strong_shock_queue_maker",
        "parameters": {
            "coin": selected_coin,
            "shock_window_ms": int(shock_window_ms),
            "shock_threshold_bps": float(shock_threshold_bps),
            "shock_cooldown_ms": int(shock_cooldown_ms),
            "maker_lifetime_ms": int(maker_lifetime_ms),
            "hold_ms": int(hold_ms),
            "notional_usd": float(notional_usd),
            "max_book_delay_ms": int(max_book_delay_ms),
        },
        "strong_shocks_seen": len(shocks),
        "maker_queue_candidates": rows,
        "placebo_candidates": placebo_rows,
        "segment_summaries": segment_summaries,
        "placebo_segment_summaries": placebo_summaries,
        "train_placebo_net_pnl_usd": placebo_summaries["train"]["net_pnl_usd"],
        "latency_evidence": dict(latency_evidence),
        "latency_measured": measured,
        "applied_latency_ms": applied_latency,
        "diagnostics": diagnostics,
        "data_sources": {
            "lead": "recorded Binance public trades",
            "execution": "recorded Hyperliquid l2Book plus public trades",
        },
        "queue_rule": "FIFO_PUBLIC_TRADES_CONSUME_AHEAD_PLUS_COMPLETE_OWN_QUANTITY",
        "cancellation_rule": "CANCELLATIONS_DO_NOT_ADVANCE_QUEUE",
        "latency_rule": "MEASURED_P95_EMBEDDED_IN_ENTRY_OR_DIAGNOSTIC_NON_LIQUIDATABLE",
        "forward_status": "NOT_STARTED_POST_FREEZE",
        "paper_read_only": True,
        "real_execution": False,
    }


__all__ = [
    "detect_rolling_shocks",
    "replay_lead_lag_queue_maker",
]
