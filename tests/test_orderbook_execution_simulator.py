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
