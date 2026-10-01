"""Fee-aware multi-venue executable prefilter for Cross-Venue research.

Consumes only synchronized public L2 snapshots. It never submits orders.
Positive rows remain candidates: a closed-cycle proof must still measure exit
depth, spread, slippage and latency.
"""
from __future__ import annotations

import math
from collections.abc import Iterable
from typing import Any

from hl_observer.collection.native_venue_market import MarketLevel, NativeMarketSnapshot
from hl_observer.config.frais_venues import frais_maker_bps, frais_taker_bps


def _walk_quote(levels: tuple[MarketLevel, ...], quote_usd: float) -> tuple[float, float] | None:
    remaining = float(quote_usd)
    base_qty = 0.0
    for level in levels:
        available_quote = float(level.price) * float(level.size)
        take_quote = min(remaining, available_quote)
        base_qty += take_quote / float(level.price)
        remaining -= take_quote
        if remaining <= 1e-10:
            break
    if remaining > 1e-8 or base_qty <= 0.0:
        return None
    return float(quote_usd) / base_qty, base_qty


def _walk_base(levels: tuple[MarketLevel, ...], base_qty: float) -> tuple[float, float] | None:
    remaining = float(base_qty)
    quote = 0.0
    for level in levels:
        take = min(remaining, float(level.size))
        quote += take * float(level.price)
        remaining -= take
        if remaining <= 1e-12:
            break
    if remaining > 1e-10 or base_qty <= 0.0:
        return None
    return quote / float(base_qty), quote


def _orientation(
    buy: NativeMarketSnapshot,
    sell: NativeMarketSnapshot,
    *,
    evidence: dict[str, float | None],
    notional_usd: float,
    execution_buffer_bps: float,
    latency_penalty_bps_per_ms: float,
) -> dict[str, Any] | None:
    if buy.coin != sell.coin or not buy.asks or not sell.bids:
        return None
    buy_fill = _walk_quote(buy.asks, notional_usd)
    if buy_fill is None:
        return None
    buy_vwap, base_qty = buy_fill
    sell_fill = _walk_base(sell.bids, base_qty)
    if sell_fill is None:
        return None
    sell_vwap, sell_proceeds = sell_fill
    buy_cost = float(notional_usd)
    gross_pnl = sell_proceeds - buy_cost
    gross_bps = gross_pnl / buy_cost * 10_000.0

    buy_taker = frais_taker_bps(buy.venue)
    sell_taker = frais_taker_bps(sell.venue)
    buy_maker = frais_maker_bps(buy.venue)
    sell_maker = frais_maker_bps(sell.venue)

    entry_fee_usd = buy_cost * buy_taker / 10_000.0 + sell_proceeds * sell_taker / 10_000.0
    entry_net = gross_pnl - entry_fee_usd
    taker_round_trip_floor = 2.0 * (buy_taker + sell_taker)
    buy_maker_round_trip_floor = 2.0 * (buy_maker + sell_taker)
    sell_maker_round_trip_floor = 2.0 * (buy_taker + sell_maker)
    both_maker_round_trip_floor = 2.0 * (buy_maker + sell_maker)

    receive_skew = evidence.get("receive_skew_ms")
    skew_ms = max(0.0, float(receive_skew)) if receive_skew is not None else 0.0
    latency_penalty = skew_ms * latency_penalty_bps_per_ms
    uncertainty_penalty = execution_buffer_bps + latency_penalty
    conservative_taker = gross_bps - taker_round_trip_floor - uncertainty_penalty

    return {
        "coin": buy.coin,
        "buy_venue": buy.venue,
        "sell_venue": sell.venue,
        "notional_usd": round(buy_cost, 8),
        "base_qty": base_qty,
        "buy_vwap": buy_vwap,
        "sell_vwap": sell_vwap,
        "gross_executable_edge_bps": gross_bps,
        "entry_taker_fee_usd": entry_fee_usd,
        "entry_taker_net_pnl_usd": entry_net,
        "entry_taker_net_edge_bps": entry_net / buy_cost * 10_000.0,
        "taker_taker_round_trip_fee_floor_bps": taker_round_trip_floor,
        "taker_taker_round_trip_net_floor_bps": gross_bps - taker_round_trip_floor,
        "buy_maker_round_trip_fee_floor_bps": buy_maker_round_trip_floor,
        "buy_maker_round_trip_net_floor_bps": gross_bps - buy_maker_round_trip_floor,
        "sell_maker_round_trip_fee_floor_bps": sell_maker_round_trip_floor,
        "sell_maker_round_trip_net_floor_bps": gross_bps - sell_maker_round_trip_floor,
        "both_maker_round_trip_fee_floor_bps": both_maker_round_trip_floor,
        "both_maker_round_trip_net_floor_bps": gross_bps - both_maker_round_trip_floor,
        "execution_buffer_bps": execution_buffer_bps,
        "latency_penalty_bps": latency_penalty,
        "conservative_taker_round_trip_net_edge_bps": conservative_taker,
        "receive_skew_ms": receive_skew,
        "corrected_exchange_skew_ms": evidence.get("corrected_exchange_skew_ms"),
        "prefilter_only": True,
        "closed_cycle_proven": False,
        "maker_fill_proven": False,
        "certification_eligible": False,
        "paper_read_only": True,
        "real_execution": False,
    }


def executable_pair_rows(
    synchronized_pairs: Iterable[tuple[NativeMarketSnapshot, NativeMarketSnapshot, dict[str, float | None]]],
    *,
    notional_usd: float,
    minimum_round_trip_edge_bps: float = 0.0,
    execution_buffer_bps: float = 0.0,
    latency_penalty_bps_per_ms: float = 0.0,
) -> list[dict[str, Any]]:
    """Evaluate both orientations and retain positive conservative fee floors."""
    notional = float(notional_usd)
    threshold = float(minimum_round_trip_edge_bps)
    buffer_bps = float(execution_buffer_bps)
    latency_rate = float(latency_penalty_bps_per_ms)
    if not math.isfinite(notional) or notional <= 0.0:
        raise ValueError("notional_usd must be finite and positive")
    if not math.isfinite(threshold):
        raise ValueError("minimum_round_trip_edge_bps must be finite")
    if not math.isfinite(buffer_bps) or buffer_bps < 0.0:
        raise ValueError("execution_buffer_bps must be finite and non-negative")
    if not math.isfinite(latency_rate) or latency_rate < 0.0:
        raise ValueError("latency_penalty_bps_per_ms must be finite and non-negative")

    rows: list[dict[str, Any]] = []
    for left, right, evidence in synchronized_pairs:
        for buy, sell in ((left, right), (right, left)):
            row = _orientation(
                buy,
                sell,
                evidence=dict(evidence),
                notional_usd=notional,
                execution_buffer_bps=buffer_bps,
                latency_penalty_bps_per_ms=latency_rate,
            )
            if row is None:
                continue
            if float(row["conservative_taker_round_trip_net_edge_bps"]) <= threshold:
                continue
            rows.append(row)
    rows.sort(
        key=lambda row: (
            float(row["conservative_taker_round_trip_net_edge_bps"]),
            float(row["gross_executable_edge_bps"]),
        ),
        reverse=True,
    )
    return rows


__all__ = ["executable_pair_rows"]
