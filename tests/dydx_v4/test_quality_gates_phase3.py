from __future__ import annotations

import time
from unittest.mock import MagicMock

from hyper_smart_observer.dydx_v4.cluster_detector import ClusterSignal, DydxClusterDetector
from hyper_smart_observer.dydx_v4.config import DydxNetwork, DydxV4Config
from hyper_smart_observer.dydx_v4.live_observer import DydxLiveObserver
from hyper_smart_observer.dydx_v4.market_flow import FlowSignal, build_cluster_from_flow


def _book(mid: float = 100.0, spread_bps: float = 2.0, size: float = 100.0) -> dict:
    half = mid * spread_bps / 2 / 10_000
    return {
        "bids": [{"price": str(mid - half), "size": str(size)} for _ in range(5)],
        "asks": [{"price": str(mid + half), "size": str(size)} for _ in range(5)],
    }


def _observer(*, max_spread_bps: float = 8.0, flow_min_trades: int = 12) -> DydxLiveObserver:
    cfg = DydxV4Config(
        network=DydxNetwork.TESTNET,
        market_flow_enabled=False,
        consensus_min_wallets=1,
        max_spread_bps=max_spread_bps,
        flow_min_trades=flow_min_trades,
        allow_market_flow_solo_entries=True,
        market_side_history_bootstrap_trades=0,
    )
    rest = MagicMock()
    rest.get_orderbook.return_value = _book()
    rest.get_candles.return_value = {"candles": []}
    rest.get_market.return_value = {"markets": {"ETH-USD": {"nextFundingRate": "0"}}}
    obs = DydxLiveObserver(
        config=cfg,
        rest_client=rest,
        cluster_detector=DydxClusterDetector(consensus_window_ms=60_000, min_notional_usdc=0.0),
        initial_shortlist=[],
        poll_interval_s=0.01,
        max_signal_age_ms=8_000,
    )
    obs._mark_prices["ETH-USD"] = 100.0
    return obs


def _flow_cluster(*, trades: int = 30, total_usdc: float = 50_000.0) -> ClusterSignal:
    buy = total_usdc if total_usdc > 0 else 0.0
    signal = FlowSignal(
        market="ETH-USD",
        direction="LONG",
        buy_usdc=buy,
        sell_usdc=0.0,
        trades=trades,
    )
    return build_cluster_from_flow(signal, mark_price=100.0, now_ms=int(time.time() * 1000))


def test_spread_gate_refuses_wide() -> None:
    obs = _observer(max_spread_bps=8.0)
    obs.rest.get_orderbook.return_value = _book(spread_bps=120.0, size=100.0)

    obs._evaluate_cluster(_flow_cluster(trades=30, total_usdc=60_000.0))

    assert obs.stats.positions_opened == 0
    assert any(reason.startswith("SPREAD_TOO_WIDE") for reason in obs._no_trade_reasons)


def test_book_too_thin_refused() -> None:
    obs = _observer(max_spread_bps=8.0)
    obs.rest.get_orderbook.return_value = _book(spread_bps=2.0, size=0.001)

    obs._evaluate_cluster(_flow_cluster(trades=30, total_usdc=60_000.0))

    assert obs.stats.positions_opened == 0
    assert any(reason.startswith("BOOK_TOO_THIN") for reason in obs._no_trade_reasons)


def test_flow_min_trades_refused() -> None:
    obs = _observer(flow_min_trades=12)

    obs._evaluate_cluster(_flow_cluster(trades=2, total_usdc=60_000.0))

    assert obs.stats.positions_opened == 0
    assert any(reason.startswith("FLOW_MIN_TRADES") for reason in obs._no_trade_reasons)




def test_weak_public_market_flow_is_context_only_by_default() -> None:
    cfg = DydxV4Config(
        network=DydxNetwork.TESTNET,
        market_flow_enabled=True,
        consensus_min_wallets=1,
        max_spread_bps=8.0,
        flow_min_trades=3,
        allow_market_flow_solo_entries=False,
        allow_strong_public_flow_paper_entries=True,
        strong_public_flow_min_volume_usdc=40_000.0,
        strong_public_flow_min_trades=8,
    )
    rest = MagicMock()
    rest.get_orderbook.return_value = _book()
    rest.get_candles.return_value = {"candles": []}
    rest.get_market.return_value = {"markets": {"ETH-USD": {"nextFundingRate": "0"}}}
    obs = DydxLiveObserver(
        config=cfg,
        rest_client=rest,
        cluster_detector=DydxClusterDetector(consensus_window_ms=60_000, min_notional_usdc=0.0),
        initial_shortlist=[],
        poll_interval_s=0.01,
        max_signal_age_ms=8_000,
    )
    obs._mark_prices["ETH-USD"] = 100.0

    obs._evaluate_cluster(_flow_cluster(trades=3, total_usdc=12_000.0))

    assert obs.stats.positions_opened == 0
    assert any(reason.startswith("PUBLIC_FLOW_CONTEXT_ONLY") for reason in obs._no_trade_reasons)


def test_strong_public_market_flow_opens_micro_paper_by_default() -> None:
    cfg = DydxV4Config(
        network=DydxNetwork.TESTNET,
        market_flow_enabled=True,
        consensus_min_wallets=1,
        max_spread_bps=8.0,
        flow_min_trades=3,
        allow_market_flow_solo_entries=False,
        allow_strong_public_flow_paper_entries=True,
        strong_public_flow_min_volume_usdc=40_000.0,
        strong_public_flow_min_trades=8,
        strong_public_flow_min_imbalance=0.70,
        paper_notional_base_usdc=75.0,
        paper_notional_min_usdc=20.0,
        paper_notional_max_usdc=100.0,
    )
    rest = MagicMock()
    rest.get_orderbook.return_value = _book(spread_bps=2.0, size=100.0)
    rest.get_candles.return_value = {"candles": []}
    rest.get_market.return_value = {"markets": {"ETH-USD": {"nextFundingRate": "0"}}}
    obs = DydxLiveObserver(
        config=cfg,
        rest_client=rest,
        cluster_detector=DydxClusterDetector(consensus_window_ms=60_000, min_notional_usdc=0.0),
        initial_shortlist=[],
        poll_interval_s=0.01,
        max_signal_age_ms=8_000,
    )
    obs._mark_prices["ETH-USD"] = 100.0

    obs._evaluate_cluster(_flow_cluster(trades=30, total_usdc=60_000.0))

    assert obs.stats.positions_opened == 1
    pos = next(iter(obs._open_positions.values()))
    assert pos.size <= cfg.paper_notional_base_usdc
    assert "STRONG_PUBLIC_FLOW" in pos.sizing_reason
    recent = obs.get_recent_decisions(limit=1, event_type="PAPER_OPEN")
    assert recent and recent[-1]["opportunity_source"] == "STRONG_PUBLIC_FLOW"


def test_market_side_loss_cooldown_blocks_repeat_entries() -> None:
    obs = _observer(flow_min_trades=12)
    now_ms = int(time.time() * 1000)
    obs._market_side_perf[("ETH-USD", "LONG")] = {
        "trades": 2,
        "wins": 0,
        "losses": 2,
        "consecutive_losses": 2,
        "net_pnl": -3.0,
        "last_closed_ms": now_ms,
        "last_loss_ms": now_ms,
        "last_win_ms": 0,
    }

    obs._evaluate_cluster(_flow_cluster(trades=30, total_usdc=80_000.0))

    assert obs.stats.positions_opened == 0
    assert any(reason.startswith("MARKET_SIDE_LOSS_COOLDOWN") for reason in obs._no_trade_reasons)


def test_market_side_requires_stronger_edge_after_cooldown() -> None:
    obs = _observer(flow_min_trades=12)
    obs.config.market_side_min_edge_after_loss_bps = 30.0
    old_loss_ms = int(time.time() * 1000) - 10 * 60 * 1000
    obs._market_side_perf[("ETH-USD", "LONG")] = {
        "trades": 2,
        "wins": 0,
        "losses": 2,
        "consecutive_losses": 2,
        "net_pnl": -3.0,
        "last_closed_ms": old_loss_ms,
        "last_loss_ms": old_loss_ms,
        "last_win_ms": 0,
    }

    obs._evaluate_cluster(_flow_cluster(trades=30, total_usdc=80_000.0))

    assert obs.stats.positions_opened == 0
    assert any(reason.startswith("MARKET_SIDE_EDGE_AFTER_LOSS") for reason in obs._no_trade_reasons)


def test_market_side_loss_history_reduces_notional_size() -> None:
    fresh = _observer(flow_min_trades=12)
    penalized = _observer(flow_min_trades=12)
    old_loss_ms = int(time.time() * 1000) - 10 * 60 * 1000
    penalized._market_side_perf[("ETH-USD", "LONG")] = {
        "trades": 1,
        "wins": 0,
        "losses": 1,
        "consecutive_losses": 1,
        "net_pnl": -1.0,
        "last_closed_ms": old_loss_ms,
        "last_loss_ms": old_loss_ms,
        "last_win_ms": 0,
    }

    cluster = _flow_cluster(trades=30, total_usdc=80_000.0)
    ctx = fresh._market_context("ETH-USD")
    fresh_notional, fresh_note = fresh._dynamic_notional(18.0, ctx, cluster)
    penalized_notional, penalized_note = penalized._dynamic_notional(18.0, ctx, cluster)

    assert penalized_notional < fresh_notional
    assert "market_side_perf=penalty" in penalized_note
    assert "market_side_perf=fresh" in fresh_note

