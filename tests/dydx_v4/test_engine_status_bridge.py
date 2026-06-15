from __future__ import annotations

from types import SimpleNamespace

from hyper_smart_observer.dydx_v4.config import DydxNetwork, DydxV4Config
from hyper_smart_observer.dydx_v4.engine import DydxEngine


def test_engine_status_exposes_observer_scan_flow_and_unrealized_pnl() -> None:
    cfg = DydxV4Config(network=DydxNetwork.TESTNET, market_flow_enabled=False)
    engine = DydxEngine(config=cfg)
    stats = SimpleNamespace(
        total_net_pnl_usdc=-0.25,
        equity=999.75,
        positions_closed=1,
        winrate=1.0,
        signals_refused=2,
        stale_signals_refused=1,
        total_fees_paid=0.05,
        winning_trades=1,
        losing_trades=0,
    )
    engine._observer = SimpleNamespace(
        stats=stats,
        _shortlist=[object(), object()],
        _open_positions={"ETH-USD:LONG": object()},
        _discovery_running=False,
        _no_trade_reasons={"SPREAD_TOO_WIDE": 1},
        _closed_trades=[{"reason": "TAKE_PROFIT"}],
        get_status=lambda: {
            "net_pnl_usdc": 1.25,
            "realized_pnl_usdc": -0.25,
            "unrealized_pnl_usdc": 1.50,
            "equity": 1001.25,
            "market_flow": {"ws_status": "SUBSCRIBED", "trades_seen": 42, "signals": 3},
            "stream": {"fills_seen": 7, "consensus_detected": 1},
            "scan": {"discovery_wallets": 2, "ws_tracked": 2, "rest_polled": 2},
        },
    )

    engine._sync_stats()
    status = engine.get_status()

    assert status["net_pnl_usdt"] == 1.25
    assert status["realized_pnl_usdt"] == -0.25
    assert status["unrealized_pnl_usdt"] == 1.50
    assert status["equity_usdt"] == 1001.25
    assert status["market_flow"]["ws_status"] == "SUBSCRIBED"
    assert status["market_flow"]["trades_seen"] == 42
    assert status["stream"]["fills_seen"] == 7
    assert status["scan"]["discovery_wallets"] == 2
    assert status["winning_trades"] == 1


def test_engine_realtime_tick_is_paper_only_and_live_marked() -> None:
    cfg = DydxV4Config(network=DydxNetwork.TESTNET, market_flow_enabled=False)
    engine = DydxEngine(config=cfg)
    refreshed = {"count": 0}

    def _refresh_marks() -> None:
        refreshed["count"] += 1

    engine._observer = SimpleNamespace(
        _mark_prices={"ETH-USD": 101.0},
        _open_positions={},
        _refresh_market_prices=_refresh_marks,
        get_status=lambda: {
            "running": True,
            "session_id": "paper-session",
            "mode": "PAPER",
            "net_pnl_usdc": 1.75,
            "realized_pnl_usdc": 0.25,
            "unrealized_pnl_usdc": 1.50,
            "equity": 1001.75,
            "total_trades": 2,
            "winning_trades": 1,
            "winrate": "50.00%",
            "shortlist_size": 3,
        },
    )

    tick = engine.get_realtime_tick()

    assert tick["paper_only"] is True
    assert tick["read_only"] is True
    assert tick["session_id"] == "paper-session"
    assert tick["net_pnl_usdt"] == 1.75
    assert tick["equity_usdt"] == 1001.75
    assert tick["open_positions"] == 0
    assert tick["prices"]["ETH-USD"] == 101.0
    assert refreshed["count"] == 1


def test_engine_realtime_tick_uses_recent_public_trade_mark_before_rest() -> None:
    cfg = DydxV4Config(network=DydxNetwork.TESTNET, market_flow_enabled=True)
    engine = DydxEngine(config=cfg)
    refreshed = {"count": 0}

    def _refresh_marks() -> None:
        refreshed["count"] += 1

    engine._observer = SimpleNamespace(
        _mark_prices={"ETH-USD": 101.0},
        _open_positions={},
        _flow_monitor=SimpleNamespace(latest_prices=lambda max_age_ms=5000: {"ETH-USD": 102.5}),
        _refresh_market_prices=_refresh_marks,
        get_status=lambda: {
            "running": True,
            "session_id": "paper-session",
            "mode": "PAPER",
            "net_pnl_usdc": 0.0,
            "realized_pnl_usdc": 0.0,
            "unrealized_pnl_usdc": 0.0,
            "equity": 1000.0,
            "shortlist_size": 1,
        },
    )

    tick = engine.get_realtime_tick()

    assert tick["paper_only"] is True
    assert tick["read_only"] is True
    assert tick["prices"]["ETH-USD"] == 102.5
    assert tick["refreshed_prices"] is True
    assert refreshed["count"] == 1
