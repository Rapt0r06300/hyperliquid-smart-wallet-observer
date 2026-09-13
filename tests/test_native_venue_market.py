from __future__ import annotations

from hl_observer.collection.native_venue_market import (
    EXPLOITABLE,
    STALE,
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
