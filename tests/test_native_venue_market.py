from __future__ import annotations

from hl_observer.collection.native_venue_market import (
    EXPLOITABLE,
    STALE,
    MarketLevel,
    MultiVenueMarketStore,
    NativeMarketSnapshot,
    canonical_coin,
)


def test_canonical_coin_normalizes_exchange_symbols() -> None:
    assert canonical_coin("BTCUSDT") == "BTC"
    assert canonical_coin("ETH-USDT-SWAP") == "ETH"
    assert canonical_coin("sol") == "SOL"


def test_snapshot_derives_mid_spread_and_rejects_stale() -> None:
    snap = NativeMarketSnapshot.build(
        venue="bybit",
        coin="BTCUSDT",
        exchange_symbol="BTCUSDT",
        bid=100.0,
        ask=100.2,
        exchange_ts_ms=1_000,
        receive_ts_ms=1_050,
        now_ms=1_100,
        stale_after_ms=500,
    )
    assert snap.quality == EXPLOITABLE
    assert snap.mid == 100.1
    assert 19.9 < snap.spread_bps < 20.1
    assert snap.real_execution is False

    stale = NativeMarketSnapshot.build(
        venue="okx",
        coin="BTC-USDT-SWAP",
        exchange_symbol="BTC-USDT-SWAP",
        bid=100.0,
        ask=100.1,
        exchange_ts_ms=1_000,
        receive_ts_ms=2_000,
        now_ms=3_000,
        stale_after_ms=500,
    )
    assert stale.quality == STALE
    assert stale.exploitable is False


def test_store_exposes_all_fresh_venues_to_cross_venue_and_lead_lag() -> None:
    store = MultiVenueMarketStore(stale_after_ms=5_000)
    for venue, bid, ask in [
        ("hyperliquid", 100.0, 100.1),
        ("binance", 100.2, 100.3),
        ("bybit", 100.4, 100.5),
        ("okx", 100.6, 100.7),
    ]:
        store.put(
            NativeMarketSnapshot.build(
                venue=venue,
                coin="BTC",
                exchange_symbol="BTC",
                bid=bid,
                ask=ask,
                exchange_ts_ms=10_000,
                receive_ts_ms=10_010,
                now_ms=10_020,
                stale_after_ms=5_000,
            )
        )

    prices = store.cross_source_prices("BTC", now_ms=10_100)
    assert {p.source for p in prices} == {"hyperliquid", "binance", "bybit", "okx"}
    rows = store.lead_lag_rows("BTC", now_ms=10_100)
    assert len(rows) == 4
    assert all(row["mid"] > 0 for row in rows)


def test_synchronized_pairs_require_receive_alignment_and_clean_integrity() -> None:
    store = MultiVenueMarketStore(stale_after_ms=5_000)
    left = NativeMarketSnapshot.build(
        venue="bybit",
        coin="BTC",
        exchange_symbol="BTCUSDT",
        bid=100.0,
        ask=100.1,
        exchange_ts_ms=10_000,
        receive_ts_ms=10_010,
        now_ms=10_020,
        stale_after_ms=5_000,
        bids=[MarketLevel(price=100.0, size=2.0)],
        asks=[MarketLevel(price=100.1, size=2.0)],
        clock_offset_ms=5.0,
    )
    right = NativeMarketSnapshot.build(
        venue="okx",
        coin="BTC",
        exchange_symbol="BTC-USDT-SWAP",
        bid=100.2,
        ask=100.3,
        exchange_ts_ms=10_008,
        receive_ts_ms=10_020,
        now_ms=10_020,
        stale_after_ms=5_000,
        bids=[MarketLevel(price=100.2, size=2.0)],
        asks=[MarketLevel(price=100.3, size=2.0)],
        clock_offset_ms=10.0,
    )
    store.put(left)
    store.put(right)

    pairs = store.synchronized_pairs(
        "BTC",
        now_ms=10_030,
        max_receive_skew_ms=50,
        max_exchange_skew_ms=50,
        require_clock_offsets=True,
        require_l2=True,
    )
    assert len(pairs) == 1
    assert pairs[0][2]["receive_skew_ms"] == 10.0
    assert pairs[0][2]["corrected_exchange_skew_ms"] == 3.0


def test_synchronized_pairs_fail_closed_on_gap_or_skew() -> None:
    store = MultiVenueMarketStore(stale_after_ms=5_000)
    store.put(
        NativeMarketSnapshot.build(
            venue="bybit",
            coin="ETH",
            exchange_symbol="ETHUSDT",
            bid=10.0,
            ask=10.1,
            exchange_ts_ms=1_000,
            receive_ts_ms=1_010,
            now_ms=1_500,
            stale_after_ms=5_000,
            gap_count=1,
        )
    )
    store.put(
        NativeMarketSnapshot.build(
            venue="okx",
            coin="ETH",
            exchange_symbol="ETH-USDT-SWAP",
            bid=10.2,
            ask=10.3,
            exchange_ts_ms=1_010,
            receive_ts_ms=1_400,
            now_ms=1_500,
            stale_after_ms=5_000,
        )
    )
    assert (
        store.synchronized_pairs(
            "ETH",
            now_ms=1_500,
            max_receive_skew_ms=250,
        )
        == []
    )
