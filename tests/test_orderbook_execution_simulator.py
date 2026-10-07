from __future__ import annotations

from hl_observer.simulation.orderbook_execution_simulator import simulate_orderbook_execution


def test_orderbook_execution_full_fill_buy():
    result = simulate_orderbook_execution(
        side="BUY",
        notional_usdc=100.0,
        mid_price=10.0,
        asks=[(10.01, 5.0), (10.02, 10.0)],
        bids=[(9.99, 10.0)],
        fee_bps=5.0,
    )

    assert result.reason == "FILLED"
    assert result.average_fill_price and result.average_fill_price > 10.0
    assert result.fee_usdc == 0.05
    assert result.slippage_bps > 0


def test_orderbook_execution_marks_partial_and_missed():
    result = simulate_orderbook_execution(
        side="SELL",
        notional_usdc=1000.0,
        mid_price=100.0,
        asks=[(100.1, 1.0)],
        bids=[(99.9, 2.0)],
        min_fill_ratio=0.8,
    )

    assert result.partial
    assert result.missed
    assert result.reason == "MISSED_FILL"
    assert result.filled_notional_usdc == 199.8


def test_orderbook_execution_marks_partial_without_miss():
    result = simulate_orderbook_execution(
        side="BUY",
        notional_usdc=100.0,
        mid_price=10.0,
        asks=[(10.0, 9.0)],
        bids=[],
        min_fill_ratio=0.8,
    )

    assert result.partial
    assert not result.missed
    assert result.reason == "PARTIAL_FILL"
    assert result.fill_ratio == 0.9


def test_orderbook_execution_rejects_stale_book_fail_closed():
    result = simulate_orderbook_execution(
        side="BUY",
        notional_usdc=100.0,
        mid_price=10.0,
        asks=[(10.01, 20.0)],
        book_age_ms=1_001,
        max_book_age_ms=1_000,
        latency_cost_bps=0.2,
        adverse_selection_bps=0.3,
        residual_impact_bps=0.1,
    )

    assert result.missed is True
    assert result.reason == "STALE_BOOK"
    assert result.replay_safe is False


def test_orderbook_execution_prices_all_measured_costs_adversely():
    result = simulate_orderbook_execution(
        side="BUY",
        notional_usdc=100.0,
        mid_price=10.0,
        asks=[(10.0, 20.0)],
        fee_bps=5.0,
        latency_cost_bps=1.0,
        adverse_selection_bps=2.0,
        residual_impact_bps=3.0,
        book_age_ms=10,
        max_book_age_ms=1_000,
    )

    assert result.average_fill_price == 10.0
    assert result.economic_fill_price == 10.006
    assert result.market_impact_bps == 3.0
    assert result.adverse_selection_bps == 2.0
    assert result.latency_cost_bps == 1.0
    assert result.all_in_cost_usdc == 0.11
    assert result.replay_safe is True


def test_orderbook_execution_is_not_economic_proof_when_costs_unmeasured():
    result = simulate_orderbook_execution(
        side="SELL",
        notional_usdc=100.0,
        mid_price=10.0,
        bids=[(10.0, 20.0)],
    )

    assert result.reason == "FILLED"
    assert result.replay_safe is False
    assert "latency_cost_bps" in result.unmeasured_costs
    assert "adverse_selection_bps" in result.unmeasured_costs
    assert "residual_impact_bps" in result.unmeasured_costs
