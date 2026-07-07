from hl_observer.backtesting.replay_engine import replay_events_with_delay
from hl_observer.backtesting.wallet_following_simulator import simulate_wallet_following


def test_same_strategy_delay_changes_event_times():
    events = [{"event_id": "a", "ts_ms": 1000, "entry_price": 100, "exit_price": 101, "side": "LONG", "coin": "HYPE", "notional_usdt": 100}]
    zero = replay_events_with_delay(events, delay_seconds=0)
    delayed = replay_events_with_delay(events, delay_seconds=60)
    assert zero[0]["effective_ts_ms"] != delayed[0]["effective_ts_ms"]


def test_wallet_following_applies_fees_and_slippage():
    result = simulate_wallet_following(
        [{"event_id": "a", "entry_price": 100, "exit_price": 101, "side": "LONG", "coin": "HYPE", "notional_usdt": 100}],
        fee_bps=4,
        slippage_bps=2,
    )
    assert len(result.trades) == 1
    assert result.equity_curve[-1] != 1000.0
