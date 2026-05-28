import pytest
from datetime import datetime, UTC
from hyper_smart_observer.backtesting.replay_engine import ReplayEngine
from hyper_smart_observer.copy_mode.copy_models import LeaderDelta, DeltaAction

def test_replay_deltas_sequence():
    engine = ReplayEngine()
    wallet = "0x1111111111111111111111111111111111111111"
    deltas = [
        LeaderDelta(
            delta_id="d1",
            leader_wallet=wallet,
            coin="BTC",
            action_type=DeltaAction.OPEN_LONG,
            observed_at=datetime(2026, 5, 24, 10, 0, tzinfo=UTC),
            leader_reference_price=60000.0
        ),
        LeaderDelta(
            delta_id="d2",
            leader_wallet=wallet,
            coin="BTC",
            action_type=DeltaAction.CLOSE_LONG,
            observed_at=datetime(2026, 5, 24, 11, 0, tzinfo=UTC),
            leader_reference_price=66000.0
        )
    ]

    report = engine.replay_deltas(wallet, deltas)

    assert report.simulated_trades == 1
    # Entry costs: Fee (0.025) + Spread/Slip (50 * 7 / 10000 = 0.035) = 0.06
    # Gross PnL: 50 * (66000-60000)/60000 = 50 * 0.1 = 5.0
    # Exit costs: 0.06
    # Net: -0.06 + 5.0 - 0.06 = 4.88
    assert report.net_pnl == pytest.approx(4.88)
