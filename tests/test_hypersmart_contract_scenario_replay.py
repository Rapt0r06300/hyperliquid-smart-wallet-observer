import pytest
import json
import os
from hyper_smart_observer.copy_mode.copy_models import LeaderDelta, DeltaAction
from datetime import datetime, UTC

@pytest.mark.contract
def test_contract_complex_scenario_loading():
    """
    Contract: Verify that a multi-step scenario fixture can be loaded and parsed.
    """
    path = "tests/fixtures/hypersmart/scenario_complex_btc.json"
    assert os.path.exists(path)
    with open(path, "r") as f:
        data = json.load(f)

    assert data["wallet"].startswith("0x")
    assert len(data["steps"]) == 4
    assert data["steps"][0]["action"] == "OPEN_LONG"

@pytest.mark.contract
def test_contract_replay_delta_sequence_stub():
    """
    Contract: ReplayEngine must handle a sequence of deltas in order.
    """
    from hyper_smart_observer.backtesting.replay_engine import ReplayEngine
    engine = ReplayEngine()

    deltas = [
        LeaderDelta(
            delta_id=f"step_{i}",
            leader_wallet="0x111",
            coin="BTC",
            action_type=DeltaAction.OPEN_LONG,
            observed_at=datetime.now(UTC),
            current_size=0.1,
            leader_reference_price=50000.0
        ) for i in range(3)
    ]

    report = engine.replay_deltas("0x111", deltas)
    # Even if stub, it should account for the number of trades
    assert report.simulated_trades == 3
    assert report.wallet_address == "0x111"
