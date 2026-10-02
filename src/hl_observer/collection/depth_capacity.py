"""Deterministic replay-grade depth/capacity tape derived from reconstructed L2.

Raw L2 remains the source of truth.  This module only creates compact immutable
features that make executable-capacity and VWAP checks cheap and auditable.
"""
from __future__ import annotations

import math
from collections.abc import Iterable, Mapping
from typing import Any

from hl_observer.collection.tick_dataset import TickEnvelope
from hl_observer.realtime.feed_quality import FeedEventKind

DEFAULT_CAPACITY_NOTIONALS_USD = (10.0, 25.0, 50.0, 100.0, 250.0, 500.0, 1000.0)
SCHEMA_VERSION = "alina.depth_capacity_tape.v1"


def _number(value: Any) -> float | None:
    try:
        parsed = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return parsed if math.isfinite(parsed) and parsed > 0.0 else None


def _level(row: Any) -> tuple[float, float] | None:
    if hasattr(row, "price") and hasattr(row, "size"):
        price = _number(getattr(row, "price"))
        size = _number(getattr(row, "size"))
    elif isinstance(row, Mapping):
        price = _number(row.get("price", row.get("p", row.get("px"))))
        size = _number(row.get("size", row.get("s", row.get("sz", row.get("q")))))
    elif isinstance(row, (list, tuple)) and len(row) >= 2:
        price = _number(row[0])
        size = _number(row[1])
    else:
        return None
    if price is None or size is None:
        return None
    return price, size


def _levels(
    rows: Iterable[Any] | None,
    *,
    reverse: bool,
    size_multiplier_to_base: float,
) -> list[tuple[float, float]]:
    parsed = [
        (price, size * size_multiplier_to_base)
        for level in (_level(row) for row in (rows or ()))
        if level is not None
        for price, size in (level,)
    ]
    parsed.sort(key=lambda item: item[0], reverse=reverse)
    return parsed


def _rounded(value: float | None) -> float | None:
    return None if value is None else round(float(value), 10)


def _walk_quote(
    levels: list[tuple[float, float]],
    target_quote_usd: float,
    *,
    reference_mid: float | None,
    side: str,
) -> dict[str, Any]:
    target = float(target_quote_usd)
    filled_quote = 0.0
    base_qty = 0.0
    worst: float | None = None
    for price, size in levels:
        if filled_quote >= target:
            break
        available_quote = price * size
        take_quote = min(target - filled_quote, available_quote)
        if take_quote <= 0.0:
            continue
        filled_quote += take_quote
        base_qty += take_quote / price
        worst = price

    vwap = filled_quote / base_qty if base_qty > 0.0 else None
    best = levels[0][0] if levels else None
    if vwap is not None and best is not None:
        incremental = (
            (vwap - best) / best * 10_000.0
            if side == "buy"
            else (best - vwap) / best * 10_000.0
        )
    else:
        incremental = None
    if vwap is not None and reference_mid is not None and reference_mid > 0.0:
        spread_cost = (
            (vwap - reference_mid) / reference_mid * 10_000.0
            if side == "buy"
            else (reference_mid - vwap) / reference_mid * 10_000.0
        )
    else:
        spread_cost = None
    ratio = min(1.0, filled_quote / target) if target > 0.0 else 0.0
    return {
        "target_notional_usd": _rounded(target),
        "filled_notional_usd": _rounded(filled_quote),
        "fill_ratio": _rounded(ratio),
        "base_qty": _rounded(base_qty),
        "executable_vwap": _rounded(vwap),
        "worst_consumed_price": _rounded(worst),
        "spread_cost_bps": _rounded(spread_cost),
        "incremental_depth_slippage_bps": _rounded(incremental),
        "cumulative_consumed_notional_usd": _rounded(filled_quote),
        "fully_fillable": bool(ratio >= 1.0 - 1e-12),
    }


def build_capacity_tape(
    bids: Iterable[Any] | None,
    asks: Iterable[Any] | None,
    *,
    notionals_usd: Iterable[float] = DEFAULT_CAPACITY_NOTIONALS_USD,
    exchange_ts_ms: int | None = None,
    receive_ts_ms: int | None = None,
    sequence: int | None = None,
    snapshot_id: int | None = None,
    size_multiplier_to_base: float = 1.0,
) -> dict[str, Any]:
    multiplier = _number(size_multiplier_to_base)
    if multiplier is None:
        raise ValueError("size_multiplier_to_base must be finite and positive")
    bid_levels = _levels(
        bids,
        reverse=True,
        size_multiplier_to_base=multiplier,
    )
    ask_levels = _levels(
        asks,
        reverse=False,
        size_multiplier_to_base=multiplier,
    )
    best_bid = bid_levels[0][0] if bid_levels else None
    best_ask = ask_levels[0][0] if ask_levels else None
    mid = (
        (best_bid + best_ask) / 2.0
        if best_bid is not None and best_ask is not None and best_ask >= best_bid
        else None
    )
    targets = tuple(
        sorted(
            {
                float(value)
                for value in notionals_usd
                if _number(value) is not None
            }
        )
    )
    buy_rows = [
        _walk_quote(ask_levels, target, reference_mid=mid, side="buy")
        for target in targets
    ]
    sell_rows = [
        _walk_quote(bid_levels, target, reference_mid=mid, side="sell")
        for target in targets
    ]
    book_age_ms = None
    if exchange_ts_ms is not None and receive_ts_ms is not None:
        delta = int(receive_ts_ms) - int(exchange_ts_ms)
        if delta >= 0:
            book_age_ms = delta
    return {
        "schema": SCHEMA_VERSION,
        "target_notionals_usd": [_rounded(value) for value in targets],
        "best_bid": _rounded(best_bid),
        "best_ask": _rounded(best_ask),
        "mid": _rounded(mid),
        "bid_level_count": len(bid_levels),
        "ask_level_count": len(ask_levels),
        "bid_available_notional_usd": _rounded(sum(price * size for price, size in bid_levels)),
        "ask_available_notional_usd": _rounded(sum(price * size for price, size in ask_levels)),
        "buy_from_asks": buy_rows,
        "sell_into_bids": sell_rows,
        "book_age_ms": book_age_ms,
        "source_sequence": int(sequence) if sequence is not None else None,
        "source_snapshot_id": int(snapshot_id) if snapshot_id is not None else None,
        "size_multiplier_to_base": _rounded(multiplier),
        "size_semantics": "raw_size_times_multiplier_equals_base_quantity",
        "complete_for_all_targets": bool(
            targets
            and buy_rows
            and sell_rows
            and all(row["fully_fillable"] for row in buy_rows + sell_rows)
        ),
        "raw_l2_source_of_truth": True,
        "paper_read_only": True,
        "real_execution": False,
    }


def capacity_tape_envelope(
    *,
    venue: str,
    instrument: str,
    bids: Iterable[Any] | None,
    asks: Iterable[Any] | None,
    exchange_ts_ms: int | None,
    received_ts_ms: int | None,
    receive_mono_ns: int | None,
    connection_id: str | None,
    sequence: int | None,
    quality: str,
    snapshot_id: int | None = None,
    gap_count: int = 0,
    timing_evidence: Mapping[str, Any] | None = None,
    size_multiplier_to_base: float | None = 1.0,
) -> TickEnvelope | None:
    if str(quality or "").upper() != "EXPLOITABLE":
        return None
    if exchange_ts_ms is None or received_ts_ms is None or receive_mono_ns is None:
        return None
    multiplier = _number(size_multiplier_to_base)
    if multiplier is None:
        return None
    tape = build_capacity_tape(
        bids,
        asks,
        exchange_ts_ms=int(exchange_ts_ms),
        receive_ts_ms=int(received_ts_ms),
        sequence=sequence,
        snapshot_id=snapshot_id,
        size_multiplier_to_base=multiplier,
    )
    if not tape["bid_level_count"] or not tape["ask_level_count"]:
        return None
    timing = dict(timing_evidence or {})
    return TickEnvelope(
        source_id=f"{str(venue).strip().lower()}_derived_capacity",
        channel="capacity_tape",
        instrument=str(instrument).strip().upper(),
        event_kind=FeedEventKind.SNAPSHOT,
        raw_payload={
            "schema": SCHEMA_VERSION,
            "derived_from_family": "l2Book",
            "source_sequence": sequence,
            "source_snapshot_id": snapshot_id,
            "source_exchange_ts_ms": int(exchange_ts_ms),
            "source_receive_mono_ns": int(receive_mono_ns),
        },
        exchange_ts_ms=int(exchange_ts_ms),
        received_ts_ms=int(received_ts_ms),
        local_monotonic_ns=int(receive_mono_ns),
        connection_id=str(connection_id) if connection_id else None,
        sequence=int(sequence) if sequence is not None else None,
        gap_count=max(0, int(gap_count)),
        provenance={
            "network": "mainnet",
            "access": "read_only",
            "transport": "derived",
            "authenticated": False,
            "real_execution": False,
            "derived": True,
            "derived_from_family": "l2Book",
            "raw_l2_source_of_truth": True,
            "derivation": "deterministic_quote_notional_depth_walk_v1",
        },
        parsed_summary={
            **tape,
            "clock_offset_ms": timing.get("clock_offset_ms", timing.get("offset_ms")),
            "clock_probe_rtt_ms": timing.get("clock_probe_rtt_ms", timing.get("rtt_ms")),
            "transport_rtt_ms": timing.get("transport_rtt_ms"),
            "timing_uncertainty_ms": timing.get("uncertainty_ms"),
            "data_gate_ready": False,
        },
    )


__all__ = [
    "DEFAULT_CAPACITY_NOTIONALS_USD",
    "SCHEMA_VERSION",
    "build_capacity_tape",
    "capacity_tape_envelope",
]
