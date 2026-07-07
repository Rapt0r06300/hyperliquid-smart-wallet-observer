from hl_observer.backtesting.execution_delay_model import apply_execution_delay
from hl_observer.backtesting.wallet_following_simulator import simulate_wallet_following


def test_backtest_e2e_uses_delay_costs_fees_slippage_and_equity_curve() -> None:
    delayed = apply_execution_delay("e1", 1_000, delay_seconds=60)
    result = simulate_wallet_following(
        [
            {
                "event_id": delayed.event_id,
                "coin": "HYPE",
                "side": "LONG",
                "entry_price": 100.0,
                "exit_price": 101.2,
                "notional_usdt": 75.0,
            }
        ],
        fee_bps=4.0,
        slippage_bps=2.0,
    )

    assert delayed.effective_ts_ms == 61_000
    assert len(result.trades) == 1
    assert result.trades[0].fee_usdt > 0
    assert len(result.equity_curve) == 2
    assert result.equity_curve[0] == 1000.0
    assert abs(result.net_pnl_usdt - (result.equity_curve[-1] - result.equity_curve[0])) < 1e-9


def test_backtest_e2e_can_report_negative_result_without_hiding_it() -> None:
    result = simulate_wallet_following(
        [
            {
                "event_id": "e2",
                "coin": "HYPE",
                "side": "LONG",
                "entry_price": 100.0,
                "exit_price": 99.0,
                "notional_usdt": 75.0,
            }
        ],
        fee_bps=4.0,
        slippage_bps=2.0,
    )

    assert result.net_pnl_usdt < 0
    assert result.equity_curve[-1] < 1000.0
