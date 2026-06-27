from __future__ import annotations

from types import SimpleNamespace

from hyper_smart_observer.dydx_v4.market_flow import (
    FlowSignal,
    MarketFlowMonitor,
    MarketFlowWindow,
    build_cluster_from_flow,
    detect_flow_signals,
    parse_trades,
)


def test_parse_trades_extracts_side_size_price_and_ignores_invalid_entries() -> None:
    contents = {
        "trades": [
            {"side": "BUY", "size": "2", "price": "100.5"},
            {"side": "sell", "size": 3, "price": 101},
            {"side": "HOLD", "size": 9, "price": 1},
            {"side": "BUY", "size": "bad", "price": 1},
            {"side": "SELL", "size": 0, "price": 1},
            "not-a-trade",
        ]
    }

    assert parse_trades(contents) == [("BUY", 2.0, 100.5), ("SELL", 3.0, 101.0)]
    assert parse_trades({"trades": "bad"}) == []
    assert parse_trades(None) == []


def test_market_flow_window_add_and_prune_removes_old_trades() -> None:
    window = MarketFlowWindow(window_ms=1000)
    window.add(1000, "ETH-USD", "BUY", 100.0)
    window.add(1500, "ETH-USD", "SELL", 200.0)
    window.add(2100, "BTC-USD", "BUY", 300.0)

    window.prune(2500)

    assert window.items() == [(1500, "ETH-USD", "SELL", 200.0), (2100, "BTC-USD", "BUY", 300.0)]


def test_detect_flow_signals_refuses_low_volume_and_low_imbalance() -> None:
    low_volume = [(1, "ETH-USD", "BUY", 100.0)]
    balanced = [
        (1, "ETH-USD", "BUY", 10_000.0),
        (2, "ETH-USD", "SELL", 9_000.0),
    ]

    assert detect_flow_signals(low_volume, min_volume_usdc=1000.0, min_imbalance=0.6) == []
    assert detect_flow_signals(balanced, min_volume_usdc=1000.0, min_imbalance=0.6) == []


def test_detect_flow_signals_emits_long_when_buy_flow_dominates() -> None:
    items = [
        (1, "SOL-USD", "BUY", 50_000.0),
        (2, "SOL-USD", "BUY", 40_000.0),
        (3, "SOL-USD", "SELL", 10_000.0),
    ]

    signals = detect_flow_signals(items, min_volume_usdc=25_000.0, min_imbalance=0.6)

    assert len(signals) == 1
    assert signals[0].market == "SOL-USD"
    assert signals[0].direction == "LONG"
    assert signals[0].total_usdc == 100_000.0
    assert signals[0].imbalance == 0.8


def test_detect_flow_signals_emits_short_when_sell_flow_dominates() -> None:
    items = [
        (1, "BTC-USD", "BUY", 20_000.0),
        (2, "BTC-USD", "SELL", 50_000.0),
        (3, "BTC-USD", "SELL", 30_000.0),
    ]

    signals = detect_flow_signals(items, min_volume_usdc=25_000.0, min_imbalance=0.6)

    assert len(signals) == 1
    assert signals[0].market == "BTC-USD"
    assert signals[0].direction == "SHORT"
    assert signals[0].trades == 3


def test_build_cluster_from_flow_preserves_stream_origin_and_freshness() -> None:
    signal = FlowSignal(
        market="ETH-USD",
        direction="LONG",
        buy_usdc=75_000.0,
        sell_usdc=5_000.0,
        trades=12,
    )

    cluster = build_cluster_from_flow(signal, mark_price=3500.0, now_ms=123456)

    assert cluster.origin == "stream"
    assert cluster.market_id == "ETH-USD"
    assert cluster.side == "LONG"
    assert cluster.is_fresh is True
    assert cluster.avg_entry_price == 3500.0
    assert cluster.total_notional_usdc == 80_000.0


def test_market_flow_monitor_refreshes_ws_status() -> None:
    monitor = MarketFlowMonitor("wss://example.invalid", ["BTC-USD"])
    monitor._ws = SimpleNamespace(
        status=SimpleNamespace(value="SUBSCRIBED"),
        is_healthy=True,
        seconds_since_last_message=0.25,
    )

    monitor._refresh_ws_stats()

    assert monitor.stats["ws_status"] == "SUBSCRIBED"
    assert monitor.stats["ws_healthy"] is True
    assert monitor.stats["seconds_since_last_message"] == 0.25


def test_market_flow_monitor_exposes_recent_trade_prices_for_mark_to_market() -> None:
    monitor = MarketFlowMonitor("wss://example.invalid", ["ETH-USD"])
    monitor._on_message(
        SimpleNamespace(
            channel="v4_trades",
            id="ETH-USD",
            data={"trades": [{"side": "BUY", "size": "1.5", "price": "2012.25"}]},
        )
    )

    prices = monitor.latest_prices(max_age_ms=5_000)

    assert prices == {"ETH-USD": 2012.25}
    assert monitor.stats["latest_price_markets"] == 1
    assert monitor.stats["last_trade_market"] == "ETH-USD"



def test_detect_flow_signals_preserves_largest_trade_on_dominant_side() -> None:
    items = [
        (1, "ETH-USD", "BUY", 65_000.0),
        (2, "ETH-USD", "BUY", 12_000.0),
        (3, "ETH-USD", "SELL", 5_000.0),
    ]

    signals = detect_flow_signals(items, min_volume_usdc=25_000.0, min_imbalance=0.6)

    assert len(signals) == 1
    assert signals[0].direction == "LONG"
    assert signals[0].large_trade_usdc == 65_000.0
    cluster = build_cluster_from_flow(signals[0], mark_price=3100.0, now_ms=456)
    assert cluster.flow_large_trade_usdc == 65_000.0


def test_market_flow_monitor_tracks_large_trade_stats() -> None:
    monitor = MarketFlowMonitor("wss://example.invalid", ["ETH-USD"], large_trade_threshold_usdc=50_000.0)
    monitor._on_message(
        SimpleNamespace(
            channel="v4_trades",
            id="ETH-USD",
            data={"trades": [{"side": "BUY", "size": "20", "price": "3100"}]},
        )
    )

    assert monitor.stats["large_trades_seen"] == 1
    assert monitor.stats["last_large_trade_market"] == "ETH-USD"
    assert monitor.stats["last_large_trade_side"] == "BUY"
    assert monitor.stats["last_large_trade_usdc"] == 62_000.0
