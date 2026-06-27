from __future__ import annotations

import time
from unittest.mock import MagicMock

import pytest

from hyper_smart_observer.dydx_v4.cluster_detector import ClusterSignal, DydxClusterDetector
from hyper_smart_observer.dydx_v4.config import DydxNetwork, DydxV4Config
from hyper_smart_observer.dydx_v4.live_observer import DydxLiveObserver
from hyper_smart_observer.dydx_v4.market_regime import (
    MarketContext,
    REGIME_CHOPPY,
    REGIME_TRENDING,
    analyze_market_context,
)


def _book(mid: float = 100.0, spread_bps: float = 2.0, size: float = 100.0) -> dict:
    half = mid * spread_bps / 2 / 10_000
    return {
        "bids": [{"price": str(mid - half), "size": str(size)} for _ in range(5)],
        "asks": [{"price": str(mid + half), "size": str(size)} for _ in range(5)],
    }


def _candles(values: list[float], volume: float = 1000.0) -> dict:
    rows = []
    for i, close in enumerate(values):
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


def _cluster(side: str = "LONG", wallets: int = 5, age_ms: int = 500) -> ClusterSignal:
    now_ms = int(time.time() * 1000)
    return ClusterSignal(
        market_id="ETH-USD",
        side=side,
        wallet_count=wallets,
        participating_wallets=[f"dydx{i}" for i in range(wallets)],
        total_notional_usdc=80_000.0,
        first_wallet_opened_ms=now_ms - age_ms,
        last_wallet_opened_ms=now_ms - 100,
        signal_age_ms=age_ms,
        avg_entry_price=100.0,
        signal_strength=0.9,
        market_priority=1.0,
        is_fresh=True,
        cluster_id=f"test-{side}-{age_ms}",
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
    return obs


def test_market_context_detects_trending_and_choppy() -> None:
    up = _candles([100 + i for i in range(30)])
    choppy_values = [100, 104, 96, 103, 97, 102, 98, 101, 99, 100] * 3
    choppy = _candles(choppy_values)

    trending = analyze_market_context("ETH-USD", up, up)
    noisy = analyze_market_context("ETH-USD", choppy, choppy)

    assert trending.regime == REGIME_TRENDING
    assert trending.edge_multiplier > 1.0
    assert noisy.regime == REGIME_CHOPPY
    assert noisy.edge_multiplier == 0.0


def test_trend_opposition_refuses_long_against_5m_and_1h_downtrend() -> None:
    rest = MagicMock()
    down = _candles([130 - i for i in range(30)])
    rest.get_candles.side_effect = [down, down]
    obs = _observer(rest=rest)

    obs._evaluate_cluster(_cluster(side="LONG"))

    assert obs.stats.positions_opened == 0
    assert "TREND_OPPOSITION" in obs._no_trade_reasons


def test_choppy_regime_refuses_before_paper_entry() -> None:
    rest = MagicMock()
    choppy_values = [100, 104, 96, 103, 97, 102, 98, 101, 99, 100] * 3
    choppy = _candles(choppy_values)
    rest.get_candles.side_effect = [choppy, choppy]
    obs = _observer(rest=rest)

    obs._evaluate_cluster(_cluster(side="LONG"))

    assert obs.stats.positions_opened == 0
    assert "CHOPPY_MARKET" in obs._no_trade_reasons


def test_dynamic_sizing_replaces_fixed_50_usdt_when_edge_is_strong() -> None:
    rest = MagicMock()
    up = _candles([100 + i for i in range(30)])
    rest.get_candles.side_effect = [up, up, up]
    obs = _observer(rest=rest)

    obs._evaluate_cluster(_cluster(side="LONG", wallets=5, age_ms=200))

    assert obs.stats.positions_opened == 1
    pos = next(iter(obs._open_positions.values()))
    assert 20.0 <= pos.size <= 100.0
    assert pos.size != pytest.approx(50.0)
    assert pos.entry_edge_bps > 0
    assert pos.market_regime == REGIME_TRENDING
    assert "dynamic edge=" in pos.sizing_reason


def test_confidence_sizing_scales_notional_by_signal_quality() -> None:
    obs = _observer()
    trending = MarketContext(market_id="ETH-USD", regime=REGIME_TRENDING, confidence=1.0)
    unknown = MarketContext(market_id="ETH-USD", confidence=0.0)

    high, high_note = obs._dynamic_notional(25.0, trending, _cluster(wallets=2, age_ms=1_000))
    medium, medium_note = obs._dynamic_notional(25.0, trending, _cluster(wallets=1, age_ms=1_000))
    low, low_note = obs._dynamic_notional(25.0, unknown, _cluster(wallets=1, age_ms=20_000))

    assert high > medium > low
    assert "confidence=HIGH:1.00" in high_note
    assert "confidence=MEDIUM:0.60" in medium_note
    assert "confidence=LOW:0.30" in low_note
