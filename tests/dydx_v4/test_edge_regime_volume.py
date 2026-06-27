from __future__ import annotations

from hyper_smart_observer.dydx_v4.edge_calculator import calculate_edge
from hyper_smart_observer.dydx_v4.market_regime import (
    MarketContext,
    REGIME_RANGING,
    REGIME_TRENDING,
)


def _edge(ctx: MarketContext):
    return calculate_edge(
        signal_age_ms=100,
        wallet_count=2,
        leader_winrate=0.60,
        leader_profit_factor=2.0,
        leader_trade_count=60,
        leader_expectancy_usdc=0.30,
        paper_notional_usdc=100.0,
        spread_bps=1.0,
        slippage_bps=1.0,
        fee_bps=1.0,
        min_edge_bps=3.0,
        market_context=ctx,
    )


def test_ranging_regime_zeroes_edge() -> None:
    ctx = MarketContext(market_id="ETH-USD", regime=REGIME_RANGING, volume_zscore=2.0, confidence=1.0)
    edge = _edge(ctx)
    assert edge.market_edge_multiplier == 0.0
    assert edge.accepted is False
    assert edge.edge_remaining_bps < 0


def test_trending_regime_boosts_edge() -> None:
    base = _edge(MarketContext(market_id="ETH-USD", confidence=1.0))
    trend = _edge(MarketContext(market_id="ETH-USD", regime=REGIME_TRENDING, confidence=1.0))
    assert trend.market_edge_multiplier == 1.2
    assert trend.edge_remaining_bps > base.edge_remaining_bps


def test_high_volume_boosts_edge_and_low_volume_penalizes() -> None:
    base = _edge(MarketContext(market_id="ETH-USD", confidence=1.0, volume_zscore=0.0))
    high = _edge(MarketContext(market_id="ETH-USD", confidence=1.0, volume_zscore=1.5))
    low = _edge(MarketContext(market_id="ETH-USD", confidence=1.0, volume_zscore=-1.5))
    assert high.market_edge_multiplier == 1.2
    assert low.market_edge_multiplier == 0.5
    assert high.edge_remaining_bps > base.edge_remaining_bps > low.edge_remaining_bps
