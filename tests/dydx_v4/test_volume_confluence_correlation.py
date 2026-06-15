from __future__ import annotations

import time
from unittest.mock import MagicMock

import pytest

from hyper_smart_observer.dydx_v4.cluster_detector import ClusterSignal, DydxClusterDetector
from hyper_smart_observer.dydx_v4.config import DydxNetwork, DydxV4Config
from hyper_smart_observer.dydx_v4.live_observer import DydxLiveObserver, PaperPositionState
from hyper_smart_observer.dydx_v4.market_regime import (
    VOLUME_SPIKE,
    correlation_group,
    is_volume_spike,
)


def _book(mid: float = 100.0, spread_bps: float = 2.0, size: float = 100.0) -> dict:
    half = mid * spread_bps / 2 / 10_000
    return {
        "bids": [{"price": str(mid - half), "size": str(size)} for _ in range(5)],
        "asks": [{"price": str(mid + half), "size": str(size)} for _ in range(5)],
    }


def _candles(values: list[float], *, spike: bool = False) -> dict:
    rows = []
    for i, close in enumerate(values):
        volume = 1000.0
        if spike and i == len(values) - 1:
            volume = 6000.0
        rows.append(
            {
                "startedAt": f"2026-01-01T00:{i:02d}:00.000Z",
                "open": str(close),
                "high": str(close * 1.002),
                "low": str(close * 0.998),
                "close": str(close),
                "baseTokenVolume": str(volume),
            }
        )
    return {"candles": rows}


def _cluster(
    market: str = "ETH-USD",
    side: str = "LONG",
    *,
    origin: str = "rest",
    strength: float = 0.9,
    wallets: int = 5,
) -> ClusterSignal:
    now_ms = int(time.time() * 1000)
    return ClusterSignal(
        market_id=market,
        side=side,
        wallet_count=wallets,
        participating_wallets=[f"dydx{i}" for i in range(wallets)],
        total_notional_usdc=90_000.0,
        first_wallet_opened_ms=now_ms - 300,
        last_wallet_opened_ms=now_ms - 100,
        signal_age_ms=300,
        avg_entry_price=100.0,
        signal_strength=strength,
        market_priority=1.0,
        is_fresh=True,
        cluster_id=f"{origin}-{market}-{side}-{now_ms}",
        origin=origin,
        flow_trade_count=30 if origin == "stream" else None,
    )


def _observer(rest: MagicMock | None = None, **cfg_overrides) -> DydxLiveObserver:
    cfg = DydxV4Config(
        network=DydxNetwork.TESTNET,
        market_flow_enabled=False,
        consensus_min_wallets=1,
        max_open_paper_trades=3,
        **cfg_overrides,
    )
    rest = rest or MagicMock()
    rest.get_orderbook.return_value = _book()
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
    obs._mark_prices["BTC-USD"] = 50_000.0
    return obs


def test_volume_spike_requires_zscore_and_imbalance() -> None:
    from hyper_smart_observer.dydx_v4.market_regime import analyze_market_context

    up = _candles([100 + i for i in range(30)], spike=True)
    ctx = analyze_market_context("ETH-USD", up, up)

    assert ctx.volume_zscore > 2.0
    assert is_volume_spike(ctx, 0.8, min_zscore=2.0, min_imbalance=0.62) is True
    assert is_volume_spike(ctx, 0.2, min_zscore=2.0, min_imbalance=0.62) is False


def test_volume_spike_marks_accepted_position_reason() -> None:
    rest = MagicMock()
    up = _candles([100 + i for i in range(30)], spike=True)
    rest.get_candles.side_effect = [up, up, up]
    obs = _observer(rest=rest)

    obs._evaluate_cluster(_cluster(side="LONG", strength=0.9))

    assert obs.stats.positions_opened == 1
    pos = next(iter(obs._open_positions.values()))
    assert VOLUME_SPIKE in pos.sizing_reason


def test_correlation_gate_refuses_same_side_major_exposure() -> None:
    obs = _observer()
    obs._open_positions["BTC-USD:LONG"] = PaperPositionState(
        position_id="p1",
        market_id="BTC-USD",
        side="LONG",
        size=80.0,
        entry_price=50_000.0,
        stop_loss_price=49_000.0,
        take_profit_price=53_000.0,
        opened_at_ms=int(time.time() * 1000),
        cluster_id="existing",
        wallet_count=3,
    )

    obs._evaluate_cluster(_cluster(market="ETH-USD", side="LONG"))

    assert correlation_group("BTC-USD") == correlation_group("ETH-USD")
    assert obs.stats.positions_opened == 0
    assert "CORRELATED_EXPOSURE" in obs._no_trade_reasons


def test_rest_flow_confluence_boost_is_logged_on_second_signal() -> None:
    rest = MagicMock()
    up = _candles([100 + i for i in range(30)])
    rest.get_candles.side_effect = [up, up, up]
    obs = _observer(rest=rest)

    now_ms = int(time.time() * 1000)
    obs._recent_signal_sources[("ETH-USD", "LONG", "flow")] = now_ms - 5000
    obs._evaluate_cluster(_cluster(origin="rest", side="LONG"))

    assert obs.stats.positions_opened == 1
    pos = next(iter(obs._open_positions.values()))
    assert "REST_FLOW_CONFLUENCE" in pos.sizing_reason
    assert pos.entry_edge_bps > 0


def test_correlation_gate_can_be_disabled_by_config() -> None:
    obs = _observer(correlation_gate_enabled=False)
    obs._open_positions["BTC-USD:LONG"] = PaperPositionState(
        position_id="p1",
        market_id="BTC-USD",
        side="LONG",
        size=80.0,
        entry_price=50_000.0,
        stop_loss_price=49_000.0,
        take_profit_price=53_000.0,
        opened_at_ms=int(time.time() * 1000),
        cluster_id="existing",
        wallet_count=3,
    )
    assert obs._correlated_exposure_reason("ETH-USD", "LONG") is None
