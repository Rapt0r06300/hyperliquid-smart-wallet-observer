from hl_observer.arbitrage import (
    CrossSourcePrice,
    PaperArbitrageLeg,
    TriangularEdge,
    build_paper_arbitrage_opportunity,
    build_triangular_cycles,
    compare_cross_source_prices,
    detect_triangular_opportunities,
    funding_adjusted_edge_bps,
    rank_paper_arbitrage_opportunities,
)
from hl_observer.edge.margin_of_safety import evaluate_margin_of_safety
from hl_observer.funding import detect_funding_spike, funding_window_stats
from hl_observer.market_signals.market_cache import MarketCache
from hl_observer.normalization.fill_aggregation import aggregate_fills_by_oid
from hl_observer.paper_trading import (
    build_delta_neutral_position,
    can_buy_amount_usdt,
    compute_funding_payment,
    reconcile_hedge_legs,
)
from hl_observer.risk import (
    kelly_size_paper,
    detect_abnormal_spread,
    detect_liquidity_cliff,
    equity_hard_stop_loss,
    tiered_copy_size,
)
from hl_observer.strategies import PaperStrategyRegistry, register_v14_profiles, v14_default_profiles


def test_v14_arbitrage_after_costs_and_ranking():
    good = build_paper_arbitrage_opportunity(
        long_leg=PaperArbitrageLeg("hyperliquid", "HYPE", "LONG", price=100, fee_bps=2, slippage_bps=1),
        short_leg=PaperArbitrageLeg("source_b", "HYPE", "SHORT", price=101, fee_bps=2, slippage_bps=1),
    )
    bad = build_paper_arbitrage_opportunity(
        long_leg=PaperArbitrageLeg("hyperliquid", "HYPE", "LONG", price=100),
        short_leg=PaperArbitrageLeg("hyperliquid", "HYPE", "SHORT", price=101),
    )

    assert good.accepted is True
    assert good.net_edge_bps > 0
    assert good.external_action is False
    assert bad.accepted is False
    assert "ARBITRAGE_REQUIRES_TWO_SOURCES" in bad.reason_codes
    assert rank_paper_arbitrage_opportunities([bad, good]) == [good]


def test_v14_cross_source_and_triangular_detection_are_paper_only():
    discrepancies = compare_cross_source_prices(
        [
            CrossSourcePrice("hl", "BTC", bid=100, ask=101),
            CrossSourcePrice("cex", "BTC", bid=103, ask=104),
        ]
    )
    assert discrepancies and discrepancies[0].coin == "BTC"

    cycles = build_triangular_cycles(
        [
            TriangularEdge("A", "B", 2.0),
            TriangularEdge("B", "C", 2.0),
            TriangularEdge("C", "A", 0.26),
        ]
    )
    opportunities = detect_triangular_opportunities(cycles, min_net_edge_bps=10, fee_bps_per_leg=1, slippage_bps_per_leg=1)
    assert opportunities
    assert opportunities[0].net_edge_bps > 0


def test_v14_funding_kelly_margin_and_risk_guards():
    funding = funding_adjusted_edge_bps(gross_edge_bps=20, funding_rate=0.001, side="SHORT")
    assert funding.adjusted_edge_bps > 20

    stats = funding_window_stats([0.001] * 20 + [0.005])
    spike = detect_funding_spike([0.001] * 20 + [0.005], sigma=2)
    assert stats.count == 21
    assert spike.spike is True

    mos = evaluate_margin_of_safety(gross_edge_bps=40, total_cost_bps=10)
    assert mos.accepted is True

    kelly = kelly_size_paper(win_probability=0.60, win_loss_ratio=1.4, equity_usdt=1000)
    assert kelly.accepted is True
    assert 0 < kelly.notional_usdt <= 50

    spread = detect_abnormal_spread(bid=100, ask=101, max_spread_bps=50)
    assert spread.ok is False

    liquidity = detect_liquidity_cliff(top_depth_usdt=100, next_depth_usdt=10000)
    assert liquidity.ok is False

    hard_stop = equity_hard_stop_loss(equity_usdt=900, start_equity_usdt=1000, max_drawdown_pct=5)
    assert hard_stop.allow_new_entries is False


def test_v14_paper_execution_helpers_and_cache():
    assert can_buy_amount_usdt(asks=((10, 2), (11, 2)), max_slippage_price=10.5) == 20

    delta = build_delta_neutral_position(coin="HYPE", long_notional_usdt=100, short_notional_usdt=99)
    assert delta.balanced is True

    funding_payment = compute_funding_payment(coin="HYPE", side="SHORT", notional_usdt=1000, funding_rate=0.001)
    assert funding_payment.pnl_usdt != 0

    hedge = reconcile_hedge_legs(leg_a_notional=100, leg_b_notional=100.1, max_skew_bps=25)
    assert hedge.ok is True

    cache = MarketCache(ttl_ms=100)
    cache.set("HYPE", {"mid": 100}, now_ms=1000)
    assert cache.get("hype", now_ms=1050) == {"mid": 100}
    assert cache.get("hype", now_ms=1200) is None


def test_v14_fill_aggregation_tiered_sizing_and_profiles():
    rows = aggregate_fills_by_oid(
        [
            {"wallet": "0xabc", "coin": "HYPE", "oid": "1", "sz": 2, "px": 10, "time": 1, "hash": "a"},
            {"wallet": "0xabc", "coin": "HYPE", "oid": "1", "sz": 3, "px": 11, "time": 2, "hash": "b"},
        ]
    )
    assert len(rows) == 1
    assert rows[0].total_size == 5
    assert rows[0].notional_usdt == 53

    sizing = tiered_copy_size(
        leader_size=100,
        leader_price=10,
        equity_usdt=1000,
        current_exposure_usdt=0,
        confidence=0.9,
        win_probability=0.62,
        win_loss_ratio=1.5,
    )
    assert sizing.accepted is True
    assert sizing.notional_usdt > 0

    registry = PaperStrategyRegistry()
    count = register_v14_profiles(registry)
    assert count == len(v14_default_profiles())
    assert all(profile.paper_only and not profile.external_action for profile in v14_default_profiles())
