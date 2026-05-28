import pytest
from hl_observer.wallets.position_delta_engine import IntelligentDeltaDetector

def test_intelligent_delta_detector_high_confidence():
    detector = IntelligentDeltaDetector()
    fill = {
        "coin": "BTC",
        "px": "60000.0",
        "sz": "0.1",
        "side": "B",
        "dir": "Open Long",
        "startPosition": "0.0",
        "closedPnl": "0.0",
        "time": 1716544800000
    }
    # previous 0 -> current 0.1 (matches sz 0.1)
    score, level, reasons = detector.evaluate_delta(fill, 0.0, 0.1)

    assert score == 1.0
    assert level == "HIGH"
    assert len(reasons) == 0

def test_intelligent_delta_detector_medium_confidence():
    detector = IntelligentDeltaDetector()
    fill = {
        "coin": "BTC",
        "px": "60000.0",
        "sz": "0.1",
        "side": "B",
        "dir": "Open Long",
        # missing startPosition
        "closedPnl": "0.0",
        "time": 1716544800000
    }
    score, level, reasons = detector.evaluate_delta(fill, 0.0, 0.1)

    # Passes: delta_vs_fill, direction_vs_side, side_match, size_match, price_valid, temporal_order, closed_pnl_logic
    # Fails: start_position_match, state_alignment
    # Total passed: 7/9
    assert score == 0.65
    assert level == "MEDIUM"

def test_intelligent_delta_detector_unknown_contradiction():
    detector = IntelligentDeltaDetector()
    fill = {
        "coin": "BTC",
        "px": "60000.0",
        "sz": "0.1",
        "side": "B",
        "dir": "Open Long",
        "startPosition": "0.0",
        "closedPnl": "0.0",
        "time": 1716544800000
    }
    # Fill says sz 0.1, but current - previous = 0.5
    score, level, reasons = detector.evaluate_delta(fill, 0.0, 0.5)

    assert level == "UNKNOWN"
    assert "CONTRADICTORY" in reasons[0]
