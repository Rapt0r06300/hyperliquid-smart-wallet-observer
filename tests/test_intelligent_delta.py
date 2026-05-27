import pytest
from hl_observer.wallets.position_delta_engine import (
    PositionAction,
    ConfidenceLevel,
)
from hl_observer.wallets.snapshot_engine import IntelligentDeltaDetector

VALID_WALLET = "0x" + "3" * 40

@pytest.fixture
def detector():
    return IntelligentDeltaDetector()

def test_high_confidence_match(detector):
    # Position change matches fill perfectly
    fill = {"coin": "BTC", "time": 1000, "side": "B", "px": "100", "sz": "1", "startPosition": "0"}
    delta = detector.detect(VALID_WALLET, "BTC", 0.0, 1.0, fill=fill)

    assert delta.action == PositionAction.OPEN
    assert delta.confidence_level == ConfidenceLevel.HIGH
    assert delta.confidence_score == 1.0
    assert delta.reason == "position_change_confirmed_by_fill"
    assert "position_change_confirmed_by_fill" in delta.notes

def test_medium_confidence_missing_fill(detector):
    # Position change exists but no fill provided
    delta = detector.detect(VALID_WALLET, "BTC", 0.0, 1.0, fill=None)

    assert delta.action == PositionAction.OPEN
    assert delta.confidence_level == ConfidenceLevel.MEDIUM
    assert delta.confidence_score == 0.65
    assert delta.reason == "position_change_without_fill"
    assert "position_change_without_fill" in delta.notes

def test_unknown_confidence_contradiction(detector):
    # Fill size contradicts position delta
    fill = {"coin": "BTC", "time": 1000, "side": "B", "px": "100", "sz": "0.5", "startPosition": "0"}
    delta = detector.detect(VALID_WALLET, "BTC", 0.0, 1.0, fill=fill)

    assert delta.action == PositionAction.UNKNOWN
    assert delta.confidence_level == ConfidenceLevel.UNKNOWN
    assert delta.reason == "fill_contradicts_position_change"
    assert any("0.5 != delta_size=1.0" in w for w in delta.warnings)

def test_unknown_confidence_flip(detector):
    # Flip is explicitly marked as UNKNOWN in requirements
    fill = {"coin": "BTC", "time": 1000, "side": "A", "px": "100", "sz": "2", "startPosition": "1"}
    delta = detector.detect(VALID_WALLET, "BTC", 1.0, -1.0, fill=fill)

    assert delta.action == PositionAction.UNKNOWN
    assert delta.confidence_level == ConfidenceLevel.UNKNOWN
    assert delta.confidence_score == 0.0
    assert delta.reason == "flip_detected_as_unknown"
    assert "flip_detected_as_unknown" in delta.notes

def test_closed_pnl_confirmation(detector):
    # Reducing action with closedPnl
    fill = {"coin": "BTC", "time": 1000, "side": "A", "px": "100", "sz": "0.5", "startPosition": "1.0", "closedPnl": "10"}
    delta = detector.detect(VALID_WALLET, "BTC", 1.0, 0.5, fill=fill)

    assert delta.action == PositionAction.REDUCE
    assert delta.confidence_level == ConfidenceLevel.HIGH

def test_closed_pnl_warning_on_open(detector):
    # closedPnl present on OPEN (weird)
    fill = {"coin": "BTC", "time": 1000, "side": "B", "px": "100", "sz": "1.0", "startPosition": "0", "closedPnl": "10"}
    delta = detector.detect(VALID_WALLET, "BTC", 0.0, 1.0, fill=fill)

    assert delta.action == PositionAction.OPEN
    assert delta.confidence_level == ConfidenceLevel.MEDIUM
    assert "closed_pnl_present_on_non_reducing_action" in delta.warnings

def test_no_change(detector):
    delta = detector.detect(VALID_WALLET, "BTC", 1.0, 1.0, fill=None)
    assert delta.action == PositionAction.UNKNOWN
    assert delta.confidence_level == ConfidenceLevel.HIGH
    assert delta.reason == "no_change_detected"
