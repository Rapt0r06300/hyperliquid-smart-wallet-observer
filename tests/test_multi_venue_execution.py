from __future__ import annotations

from hl_observer.arbitrage.multi_venue_execution import executable_pair_rows
from hl_observer.collection.native_venue_market import MarketLevel, NativeMarketSnapshot


def _snap(venue: str, bid: float, ask: float):
    return NativeMarketSnapshot.build(
        venue=venue,
        coin="BTC",
        exchange_symbol="BTC",
        bid=bid,
        ask=ask,
        exchange_ts_ms=1_000,
        receive_ts_ms=1_010,
        now_ms=1_020,
        stale_after_ms=1_000,
        bids=(MarketLevel(bid, 10.0),),
        asks=(MarketLevel(ask, 10.0),),
    )


def test_fee_aware_prefilter_uses_exact_depth_and_four_leg_fee_floor():
    hl = _snap("hyperliquid", 99.9, 100.0)
    okx = _snap("okx", 101.5, 101.6)
    rows = executable_pair_rows(
        [(hl, okx, {"receive_skew_ms": 0.0, "corrected_exchange_skew_ms": None})],
        notional_usd=100.0,
    )
    assert len(rows) == 1
    row = rows[0]
    assert row["buy_venue"] == "hyperliquid"
    assert row["sell_venue"] == "okx"
    assert row["gross_executable_edge_bps"] > 149.0
    assert row["taker_taker_round_trip_fee_floor_bps"] == 19.0
    assert row["taker_taker_round_trip_net_floor_bps"] > 130.0
    assert row["closed_cycle_proven"] is False
    assert row["certification_eligible"] is False


def test_maker_diagnostic_lowers_fee_floor_without_claiming_fill():
    hl = _snap("hyperliquid", 99.9, 100.0)
    bybit = _snap("bybit", 100.4, 100.5)
    rows = executable_pair_rows(
        [(hl, bybit, {"receive_skew_ms": 0.0, "corrected_exchange_skew_ms": None})],
        notional_usd=100.0,
        minimum_round_trip_edge_bps=-100.0,
    )
    row = next(
        item for item in rows
        if item["buy_venue"] == "hyperliquid" and item["sell_venue"] == "bybit"
    )
    assert row["buy_maker_round_trip_fee_floor_bps"] < row["taker_taker_round_trip_fee_floor_bps"]
    assert row["both_maker_round_trip_fee_floor_bps"] < row["buy_maker_round_trip_fee_floor_bps"]
    assert row["maker_fill_proven"] is False


def test_depth_exhaustion_fails_closed():
    hl = NativeMarketSnapshot.build(
        venue="hyperliquid",
        coin="BTC",
        exchange_symbol="BTC",
        bid=99.9,
        ask=100.0,
        exchange_ts_ms=1_000,
        receive_ts_ms=1_010,
        now_ms=1_020,
        stale_after_ms=1_000,
        bids=(MarketLevel(99.9, 0.1),),
        asks=(MarketLevel(100.0, 0.1),),
    )
    okx = _snap("okx", 101.5, 101.6)
    assert executable_pair_rows(
        [(hl, okx, {"receive_skew_ms": 0.0, "corrected_exchange_skew_ms": None})],
        notional_usd=100.0,
    ) == []
