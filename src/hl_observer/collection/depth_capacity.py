"""Deterministic replay-grade depth/capacity tape derived from reconstructed L2.

Raw L2 remains the source of truth.  This module only creates compact immutable
features that make executable-capacity and VWAP checks cheap and auditable.
"""
from __future__ import annotations

import math
import hashlib
import json
from collections.abc import Iterable, Mapping
from typing import Any

from hl_observer.collection.tick_dataset import TickEnvelope
from hl_observer.collection.native_venue_market import canonical_coin
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


def _sha256_json(value: Any) -> str:
    encoded = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


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
    levels_consumed = 0
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
        levels_consumed += 1

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
    fully_fillable = bool(ratio >= 1.0 - 1e-12)
    return {
        "side": side.upper(),
        "target_notional_usd": _rounded(target),
        "requested_notional_usd": _rounded(target),
        "filled_notional_usd": _rounded(filled_quote),
        "fill_ratio": _rounded(ratio),
        "base_qty": _rounded(base_qty),
        "cumulative_depth_base_qty": _rounded(base_qty),
        "executable_vwap": _rounded(vwap),
        "worst_consumed_price": _rounded(worst),
        "spread_cost_bps": _rounded(spread_cost),
        "incremental_depth_slippage_bps": _rounded(incremental),
        "cumulative_consumed_notional_usd": _rounded(filled_quote),
        "levels_consumed": levels_consumed,
        "fully_fillable": fully_fillable,
        "quality_status": "CERTIFIABLE" if fully_fillable else "UNMEASURABLE",
        "failure_reason": None if fully_fillable else "INSUFFICIENT_DEPTH",
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
    reconstructed_book_sha256 = _sha256_json(
        {
            "bids": bid_levels,
            "asks": ask_levels,
            "exchange_ts_ms": exchange_ts_ms,
            "receive_ts_ms": receive_ts_ms,
            "sequence": sequence,
            "snapshot_id": snapshot_id,
            "size_multiplier_to_base": multiplier,
        }
    )
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
        "source_reconstructed_book_sha256": reconstructed_book_sha256,
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


def _rows_by_target(rows: Any) -> dict[float, Mapping[str, Any]]:
    if not isinstance(rows, list):
        return {}
    result: dict[float, Mapping[str, Any]] = {}
    for row in rows:
        if not isinstance(row, Mapping):
            continue
        target = _number(row.get("target_notional_usd"))
        if target is not None:
            result[target] = row
    return result


def _paired_direction(
    *,
    entry_a: Mapping[str, Any],
    entry_b: Mapping[str, Any],
    exit_a: Mapping[str, Any],
    exit_b: Mapping[str, Any],
    entry_capacity_a: float,
    entry_capacity_b: float,
    exit_capacity_a: float,
    exit_capacity_b: float,
) -> dict[str, Any]:
    targets = sorted(set(entry_a) & set(entry_b) & set(exit_a) & set(exit_b))
    target_rows = []
    for target in targets:
        entry_fill = min(
            float(entry_a[target].get("filled_notional_usd") or 0.0),
            float(entry_b[target].get("filled_notional_usd") or 0.0),
        )
        exit_fill = min(
            float(exit_a[target].get("filled_notional_usd") or 0.0),
            float(exit_b[target].get("filled_notional_usd") or 0.0),
        )
        entry_ok = bool(entry_a[target].get("fully_fillable")) and bool(
            entry_b[target].get("fully_fillable")
        )
        exit_ok = bool(exit_a[target].get("fully_fillable")) and bool(
            exit_b[target].get("fully_fillable")
        )
        target_rows.append(
            {
                "target_notional_usd": _rounded(target),
                "entry_filled_notional_usd": _rounded(entry_fill),
                "entry_fill_ratio": _rounded(entry_fill / target),
                "entry_quality_status": "CERTIFIABLE" if entry_ok else "UNMEASURABLE",
                "exit_filled_notional_usd": _rounded(exit_fill),
                "exit_fill_ratio": _rounded(exit_fill / target),
                "exit_quality_status": "CERTIFIABLE" if exit_ok else "UNMEASURABLE",
                "round_trip_capacity_certifiable": entry_ok and exit_ok,
            }
        )
    return {
        "entry_capacity_leg_a_usd": _rounded(entry_capacity_a),
        "entry_capacity_leg_b_usd": _rounded(entry_capacity_b),
        "entry_simultaneous_capacity_usd": _rounded(min(entry_capacity_a, entry_capacity_b)),
        "exit_capacity_leg_a_usd": _rounded(exit_capacity_a),
        "exit_capacity_leg_b_usd": _rounded(exit_capacity_b),
        "exit_simultaneous_capacity_usd": _rounded(min(exit_capacity_a, exit_capacity_b)),
        "target_rows": target_rows,
    }


def build_cross_venue_capacity_tape(
    *,
    venue_a: str,
    instrument_a: str,
    tape_a: Mapping[str, Any],
    receive_mono_ns_a: int | None,
    venue_b: str,
    instrument_b: str,
    tape_b: Mapping[str, Any],
    receive_mono_ns_b: int | None,
    max_receive_skew_ns: int = 250_000_000,
) -> dict[str, Any] | None:
    """Compose two same-runner capacity tapes without re-walking either book."""
    coin_a = canonical_coin(instrument_a)
    coin_b = canonical_coin(instrument_b)
    if not coin_a or coin_a != coin_b:
        return None
    if receive_mono_ns_a is None or receive_mono_ns_b is None:
        return None
    skew = abs(int(receive_mono_ns_a) - int(receive_mono_ns_b))
    if skew > max(0, int(max_receive_skew_ns)):
        return None

    a_buy = _rows_by_target(tape_a.get("buy_from_asks"))
    a_sell = _rows_by_target(tape_a.get("sell_into_bids"))
    b_buy = _rows_by_target(tape_b.get("buy_from_asks"))
    b_sell = _rows_by_target(tape_b.get("sell_into_bids"))
    if not a_buy or not a_sell or not b_buy or not b_sell:
        return None
    a_ask = float(tape_a.get("ask_available_notional_usd") or 0.0)
    a_bid = float(tape_a.get("bid_available_notional_usd") or 0.0)
    b_ask = float(tape_b.get("ask_available_notional_usd") or 0.0)
    b_bid = float(tape_b.get("bid_available_notional_usd") or 0.0)
    return {
        "schema": "alina.cross_venue_capacity_tape.v1",
        "coin": coin_a,
        "venue_a": str(venue_a).strip().lower(),
        "instrument_a": str(instrument_a).strip().upper(),
        "venue_b": str(venue_b).strip().lower(),
        "instrument_b": str(instrument_b).strip().upper(),
        "receive_skew_ns": skew,
        "max_receive_skew_ns": int(max_receive_skew_ns),
        "directions": {
            "BUY_A_SELL_B": _paired_direction(
                entry_a=a_buy,
                entry_b=b_sell,
                exit_a=a_sell,
                exit_b=b_buy,
                entry_capacity_a=a_ask,
                entry_capacity_b=b_bid,
                exit_capacity_a=a_bid,
                exit_capacity_b=b_ask,
            ),
            "BUY_B_SELL_A": _paired_direction(
                entry_a=b_buy,
                entry_b=a_sell,
                exit_a=b_sell,
                exit_b=a_buy,
                entry_capacity_a=b_ask,
                entry_capacity_b=a_bid,
                exit_capacity_a=b_bid,
                exit_capacity_b=a_ask,
            ),
        },
        "derived_only": True,
        "raw_l2_source_of_truth": True,
        "paper_read_only": True,
        "real_execution": False,
    }


def cross_venue_capacity_envelope(
    left: TickEnvelope,
    right: TickEnvelope,
    *,
    max_receive_skew_ns: int = 250_000_000,
) -> TickEnvelope | None:
    if left.channel != "capacity_tape" or right.channel != "capacity_tape":
        return None
    left_venue = str(left.parsed_summary.get("venue") or "").lower()
    right_venue = str(right.parsed_summary.get("venue") or "").lower()
    if not left_venue or not right_venue or left_venue == right_venue:
        return None
    first, second = (
        (left, right)
        if (left_venue, left.instrument) <= (right_venue, right.instrument)
        else (right, left)
    )
    tape = build_cross_venue_capacity_tape(
        venue_a=str(first.parsed_summary.get("venue") or ""),
        instrument_a=first.instrument,
        tape_a=first.parsed_summary,
        receive_mono_ns_a=first.local_monotonic_ns,
        venue_b=str(second.parsed_summary.get("venue") or ""),
        instrument_b=second.instrument,
        tape_b=second.parsed_summary,
        receive_mono_ns_b=second.local_monotonic_ns,
        max_receive_skew_ns=max_receive_skew_ns,
    )
    if tape is None:
        return None
    source_legs = [
        {
            "venue": str(row.parsed_summary.get("venue") or ""),
            "instrument": row.instrument,
            "exchange_ts_ms": row.exchange_ts_ms,
            "receive_wall_ts_ms": row.received_ts_ms,
            "receive_monotonic_ns": row.local_monotonic_ns,
            "source_raw_l2_sha256": row.parsed_summary.get("source_raw_l2_sha256"),
            "source_reconstructed_book_sha256": row.parsed_summary.get(
                "source_reconstructed_book_sha256"
            ),
        }
        for row in (first, second)
    ]
    # Two venues have independent exchange clocks; max(exchange timestamps)
    # is NOT the event time of a synthesized cross-venue observation. Preserve
    # both authentic leg timestamps in source_legs and use the actual receiver
    # clock of the second available leg for causal replay.
    return TickEnvelope(
        source_id="cross_venue_derived_capacity",
        channel="cross_venue_capacity_tape",
        instrument=str(tape["coin"]),
        event_kind=FeedEventKind.SNAPSHOT,
        raw_payload={"schema": tape["schema"], "source_legs": source_legs},
        exchange_ts_ms=None,
        received_ts_ms=max(first.received_ts_ms, second.received_ts_ms),
        local_monotonic_ns=max(
            int(first.local_monotonic_ns or 0),
            int(second.local_monotonic_ns or 0),
        ),
        connection_id=None,
        sequence=None,
        gap_count=max(0, int(first.gap_count)) + max(0, int(second.gap_count)),
        provenance={
            "network": "mainnet",
            "access": "read_only",
            "transport": "derived",
            "authenticated": False,
            "real_execution": False,
            "derived": True,
            "derived_from_family": "capacity_tape",
            "timestamp_semantics": "receive_observation_time_only",
            "raw_l2_source_of_truth": True,
            "derivation": "same_runner_minimum_two_leg_capacity_v1",
        },
        parsed_summary={**tape, "source_legs": source_legs, "data_gate_ready": False},
    )


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
    source_raw_l2_payload: Any | None = None,
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
    raw_l2_sha256 = (
        _sha256_json(source_raw_l2_payload)
        if source_raw_l2_payload is not None
        else None
    )
    source_identity = {
        "venue": str(venue).strip().lower(),
        "instrument": str(instrument).strip().upper(),
        "exchange_ts_ms": int(exchange_ts_ms),
        "receive_wall_ts_ms": int(received_ts_ms),
        "receive_monotonic_ns": int(receive_mono_ns),
        "sequence": int(sequence) if sequence is not None else None,
        "snapshot_id": int(snapshot_id) if snapshot_id is not None else None,
        "raw_l2_sha256": raw_l2_sha256,
        "reconstructed_book_sha256": tape["source_reconstructed_book_sha256"],
    }
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
            "source_raw_l2_sha256": raw_l2_sha256,
            "source_reconstructed_book_sha256": tape["source_reconstructed_book_sha256"],
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
            "source_raw_l2_sha256": raw_l2_sha256,
            "source_reconstructed_book_sha256": tape["source_reconstructed_book_sha256"],
        },
        parsed_summary={
            **tape,
            "venue": str(venue).strip().lower(),
            "instrument": str(instrument).strip().upper(),
            "coin": canonical_coin(instrument),
            "exchange_ts_ms": int(exchange_ts_ms),
            "receive_wall_ts_ms": int(received_ts_ms),
            "receive_monotonic_ns": int(receive_mono_ns),
            "source_raw_l2_sha256": raw_l2_sha256,
            "source_l2_identity": source_identity,
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
    "build_cross_venue_capacity_tape",
    "capacity_tape_envelope",
    "cross_venue_capacity_envelope",
]
