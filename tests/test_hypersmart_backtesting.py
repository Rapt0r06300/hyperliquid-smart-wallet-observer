from hyper_smart_observer.backtesting.replay_engine import ReplayEngine
from hyper_smart_observer.backtesting.multi_wallet_simulator import simulate_multi_wallet_following


def test_backtest_applies_costs_and_latency_warning():
    report = ReplayEngine().replay_closed_pnl("0x" + "a" * 40, [10.0, -2.0])

    assert report.simulated_trades == 2
    assert report.net_pnl < 8.0
    assert "local simulation" in report.disclaimer.lower()


def test_multi_wallet_follow_simulation_aggregates_after_costs():
    wallet_a = "0x" + "a" * 40
    wallet_b = "0x" + "b" * 40
    report = simulate_multi_wallet_following(
        {
            wallet_a: [
                {"closed_pnl": 10.0, "price": 100.0, "size": 1.0},
                {"closed_pnl": -2.0, "price": 100.0, "size": 1.0},
            ],
            wallet_b: [
                {"closed_pnl": 5.0, "price": 50.0, "size": 2.0},
                {"closed_pnl": None, "price": 50.0, "size": 2.0},
            ],
        },
        notional_per_trade=50.0,
        fee_bps=5.0,
        spread_bps=2.0,
        slippage_bps=5.0,
        delay_seconds=300.0,
    )

    assert report.requested_wallets == 2
    assert report.simulated_wallets == 2
    assert report.total_usable_trades == 3
    assert report.total_skipped_actions == 1
    assert report.total_costs > 0
    assert report.net_pnl < report.gross_pnl
    assert "not a trading signal" in report.disclaimer.lower()


def test_multi_wallet_follow_simulation_refuses_empty_data():
    wallet = "0x" + "c" * 40
    report = simulate_multi_wallet_following({wallet: []})

    assert report.simulated_wallets == 0
    assert report.total_usable_trades == 0
    assert report.warnings
