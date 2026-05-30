import pytest
from hl_observer.wallets.position_delta_engine import (
    PositionAction,
    ConfidenceLevel,
    PositionSide,
)
from hl_observer.wallets.snapshot_engine import IntelligentDeltaDetector
from hl_observer.wallets.position_rebuilder import rebuild_positions_from_fills

VALID_WALLET = "0x" + "3" * 40

@pytest.fixture
def detector():
    return IntelligentDeltaDetector()

def test_omnipotent_funding_proof(detector):
    # entry 100, exit 105, size 1.0 (Long) -> realized PnL 5.0
    # but we had funding rate of 0.01. funding = 0.01 * 1.0 * 100 = 1.0.
    # Total closedPnl = 5.0 - 1.0 = 4.0.
    fill = {"coin": "BTC", "time": 1000, "side": "A", "sz": "1.0", "px": "105", "startPosition": "1.0", "closedPnl": "4.0"}
    delta = detector.detect(VALID_WALLET, "BTC", 1.0, 0.0, fills=[fill], entry_price=100.0, funding_rate=0.01)

    assert delta.source_evidence["scorecard"]["funding_pnl_sanity"] is True
    assert delta.confidence_level == ConfidenceLevel.HIGH

def test_omnipotent_narrative_generation(detector):
    fill = {"coin": "BTC", "time": 1000, "side": "B", "px": "101", "sz": "1.0", "startPosition": "0"}
    delta = detector.detect(VALID_WALLET, "BTC", 0.0, 1.0, fills=[fill], mid_price=100.0)

    assert "Leader opened a LONG position on BTC" in delta.trade_narrative
    assert "intent: AGGRESSIVE" in delta.trade_narrative

def test_omnipotent_rebuilder_flip_decomposition():
    # Test that rebuilder emits TWO deltas for one flip fill
    fill = {"coin": "BTC", "time": 1000, "side": "A", "sz": "2.0", "px": "100", "startPosition": "1.0"}
    result = rebuild_positions_from_fills(VALID_WALLET, [fill])

    # We expect 2 deltas: CLOSE long, then OPEN short
    assert len(result.deltas) == 2
    assert result.deltas[0].action == PositionAction.CLOSE
    assert result.deltas[1].action == PositionAction.OPEN
    assert result.deltas[1].new_side == PositionSide.SHORT

def test_omnipotent_subset_limit_reconciliation(detector):
    # 5 fills, but only a subset of 3 matches the delta
    fills = [
        {"coin": "BTC", "time": 1000, "side": "B", "sz": "0.1", "px": "100"},
        {"coin": "BTC", "time": 1010, "side": "B", "sz": "0.2", "px": "100"},
        {"coin": "BTC", "time": 1020, "side": "B", "sz": "0.3", "px": "100"}, # Target subset sum 0.6
        {"coin": "BTC", "time": 1030, "side": "B", "sz": "5.0", "px": "100"}, # Noise
        {"coin": "BTC", "time": 1040, "side": "B", "sz": "10.0", "px": "100"}, # Noise
    ]
    delta = detector.detect(VALID_WALLET, "BTC", 0.0, 0.6, fills=fills)
    assert delta.confidence_level == ConfidenceLevel.HIGH
    assert delta.source_evidence["fills_reconciled"] == 3
    assert delta.fill_size == 0.6
