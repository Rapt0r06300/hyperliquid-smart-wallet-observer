import pytest
from datetime import datetime, UTC, timedelta
from hyper_smart_observer.copy_mode.consensus import detect_position_consensus
from hyper_smart_observer.copy_mode.copy_models import LeaderDelta, DeltaAction

@pytest.mark.contract
def test_contract_position_consensus_detection():
    """
    Contract: Consensus must be detected when multiple wallets take the same direction.
    """
    now = datetime.now(UTC)
    deltas = [
        LeaderDelta(
            delta_id="d1", leader_wallet="0x111", coin="BTC",
            action_type=DeltaAction.OPEN_LONG, observed_at=now
        ),
        LeaderDelta(
            delta_id="d2", leader_wallet="0x222", coin="BTC",
            action_type=DeltaAction.OPEN_LONG, observed_at=now + timedelta(seconds=10)
        ),
    ]

    results = detect_position_consensus(deltas, min_wallets=2, window_seconds=300)
    assert len(results) == 1
    consensus = results[0]
    assert consensus.coin == "BTC"
    assert consensus.direction == "LONG"
    assert consensus.wallet_count == 2
    assert "0x111" in consensus.wallets
    assert "0x222" in consensus.wallets

@pytest.mark.contract
def test_contract_position_consensus_crowding_risk():
    """
    Contract: High wallet count should trigger high crowding risk.
    """
    now = datetime.now(UTC)
    deltas = [
        LeaderDelta(delta_id=f"d{i}", leader_wallet=f"0x{i}", coin="ETH",
                    action_type=DeltaAction.OPEN_SHORT, observed_at=now)
        for i in range(1, 6) # 5 wallets
    ]

    results = detect_position_consensus(deltas, min_wallets=2)
    assert len(results) == 1
    assert results[0].crowding_risk == "HIGH"
    assert "crowding_risk_many_wallets_same_direction" in results[0].warnings
