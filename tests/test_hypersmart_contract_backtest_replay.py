import pytest
from hyper_smart_observer.backtesting.replay_engine import ReplayEngine

def test_replay_closed_pnl_basic():
    engine = ReplayEngine()
    pnls = [10.0, -5.0, 15.0]
    report = engine.replay_closed_pnl("0x1111111111111111111111111111111111111111", pnls)

    assert report.simulated_trades == 3
    # Fee is 5 bps of 50.0 = 0.025 per trade
    # Net: (10.0-0.025) + (-5.0-0.025) + (15.0-0.025) = 20.0 - 0.075 = 19.925
    assert report.net_pnl == pytest.approx(19.925)
