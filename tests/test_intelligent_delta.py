import pytest
from hl_observer.wallets.position_delta_engine import (
    PositionAction,
    ConfidenceLevel,
    PositionSide,
)
from hl_observer.wallets.snapshot_engine import IntelligentDeltaDetector

VALID_WALLET = "0x" + "3" * 40

@pytest.fixture
def detector():
    return IntelligentDeltaDetector()

def test_god_mode_flip_decomposition(detector):
    # Flip from +1.0 to -1.0 with a single fill of 2.0
    fill = {"coin": "BTC", "time": 1000, "side": "A", "sz": "2.0", "startPosition": "1.0", "px": "100"}
    delta = detector.detect(VALID_WALLET, "BTC", 1.0, -1.0, fills=[fill])

    assert delta.action == PositionAction.UNKNOWN
    assert delta.reason == "flip_decomposed_as_unknown"
    assert len(delta.sub_actions) == 2
    assert delta.sub_actions[0]["action"] == PositionAction.CLOSE
    assert delta.sub_actions[1]["action"] == PositionAction.OPEN
    assert delta.sub_actions[1]["side"] == PositionSide.SHORT

def test_god_mode_pnl_proof_match(detector):
    # Short position closed with a profit
    # entry=110, exit=100, size=1.0 -> PnL = (110 - 100) * 1.0 = +10.0
    # In my code: pnl = (avg_price - entry_price) * abs(delta_size) * dir_mult
    # dir_mult for SHORT is -1. (100 - 110) * 1.0 * -1 = +10.0
    fill = {"coin": "BTC", "time": 1000, "side": "B", "px": "100", "sz": "1.0", "startPosition": "-1.0", "closedPnl": "10.0"}
    delta = detector.detect(VALID_WALLET, "BTC", -1.0, 0.0, fills=[fill], entry_price=110.0)

    assert delta.source_evidence["scorecard"]["pnl_mathematical_proof"] is True
    assert delta.confidence_level == ConfidenceLevel.HIGH

def test_god_mode_intent_aggressive(detector):
    # Mid=100, buying at 101 -> Aggressive
    fill = {"coin": "BTC", "time": 1000, "side": "B", "px": "101", "sz": "1.0", "startPosition": "0"}
    delta = detector.detect(VALID_WALLET, "BTC", 0.0, 1.0, fills=[fill], mid_price=100.0)
    assert delta.intent == "AGGRESSIVE"

def test_god_mode_intent_passive(detector):
    # Mid=100, buying at 99 -> Passive (limit order)
    fill = {"coin": "BTC", "time": 1000, "side": "B", "px": "99", "sz": "1.0", "startPosition": "0"}
    delta = detector.detect(VALID_WALLET, "BTC", 0.0, 1.0, fills=[fill], mid_price=100.0)
    assert delta.intent == "PASSIVE"

def test_god_mode_sequence_gap(detector):
    # Gap in startPosition sequence
    f1 = {"coin": "BTC", "time": 1000, "side": "B", "sz": "1.0", "startPosition": "0"}
    f2 = {"coin": "BTC", "time": 1100, "side": "B", "sz": "1.0", "startPosition": "5.0"} # Gap: 0+1=1 != 5
    delta = detector.detect(VALID_WALLET, "BTC", 0.0, 2.0, fills=[f1, f2])

    assert delta.source_evidence["scorecard"]["fill_sequence_continuity"] is False
    assert any("fill_sequence_gap" in w for w in delta.warnings)
