import pytest
from hyper_smart_observer.backtesting.replay_engine import ReplayEngine
from hyper_smart_observer.copy_mode.copy_models import LeaderDelta, DeltaAction, utc_now

@pytest.mark.contract
def test_contract_replay_engine_methods():
    """
    Contract: Replay engine must support delta-based replay.
    """
    engine = ReplayEngine()
    assert hasattr(engine, 'replay_deltas'), "Contract: ReplayEngine must have replay_deltas"

    # Test stub call
    delta = LeaderDelta(
        delta_id="test",
        leader_wallet="0x111",
        coin="BTC",
        action_type=DeltaAction.OPEN_LONG,
        observed_at=utc_now()
    )
    report = engine.replay_deltas("0x111", [delta])
    assert report.simulated_trades == 1
    assert "Stub replay" in report.warnings[0]
