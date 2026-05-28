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

def test_grandmaster_subset_sum_match(detector):
    # We have 3 fills, but only a subset of 2 matches the delta of +1.0
    # One fill is "noisy" or belongs to a different snapshot period
    fill1 = {"coin": "BTC", "time": 1000, "side": "B", "px": "100", "sz": "0.6", "startPosition": "0", "dir": "Open Long"}
    fill2 = {"coin": "BTC", "time": 1100, "side": "B", "px": "110", "sz": "0.4", "startPosition": "0.6", "dir": "Open Long"}
    fill_noisy = {"coin": "BTC", "time": 1200, "side": "B", "px": "120", "sz": "5.0", "startPosition": "1.0", "dir": "Add Long"}

    # Delta is +1.0, fills total 6.0, but subset {fill1, fill2} matches 1.0 exactly
    delta = detector.detect(VALID_WALLET, "BTC", 0.0, 1.0, fills=[fill1, fill2, fill_noisy])

    assert delta.action == PositionAction.OPEN
    # exact failed, but subset matched
    assert delta.confidence_level == ConfidenceLevel.HIGH
    assert "matched_subset_of_2_fills_out_of_3" in delta.notes
    assert delta.fill_size == 1.0

def test_grandmaster_precision_tolerance(detector):
    # Match with small precision difference (1e-8)
    fill = {"coin": "BTC", "time": 1000, "side": "B", "px": "100", "sz": str(1.0 + 1e-8), "startPosition": "0"}
    delta = detector.detect(VALID_WALLET, "BTC", 0.0, 1.0, fills=[fill])
    assert delta.confidence_level == ConfidenceLevel.HIGH

def test_grandmaster_entropy_heavy_contradiction(detector):
    # Multiple proof contradictions (side, sz, startPos)
    fill = {"coin": "BTC", "time": 1000, "side": "A", "px": "100", "sz": "5.0", "startPosition": "10"}
    delta = detector.detect(VALID_WALLET, "BTC", 0.0, 1.0, fills=[fill])

    assert delta.action == PositionAction.UNKNOWN
    assert delta.confidence_level == ConfidenceLevel.UNKNOWN
    assert "contradiction_detected" in delta.reason
    assert "side_consistency" in delta.reason

def test_grandmaster_mid_price_sanity(detector):
    fill = {"coin": "BTC", "time": 1000, "side": "B", "px": "100", "sz": "1.0", "startPosition": "0"}
    # 110 vs 100 is 10% deviation (limit is 5%)
    delta = detector.detect(VALID_WALLET, "BTC", 0.0, 1.0, fills=[fill], mid_price=110.0)
    assert delta.source_evidence["scorecard"]["market_price_sanity"] is False
    assert any("price_deviation_high" in w for w in delta.warnings)

def test_grandmaster_no_fills(detector):
    delta = detector.detect(VALID_WALLET, "BTC", 0.0, 1.0, fills=None)
    assert delta.confidence_level == ConfidenceLevel.MEDIUM
    assert delta.reason == "position_change_without_fill"

def test_grandmaster_flip(detector):
    fill = {"coin": "BTC", "time": 1000, "side": "A", "sz": "2", "startPosition": "1", "px": "100"}
    delta = detector.detect(VALID_WALLET, "BTC", 1.0, -1.0, fills=[fill])
    assert delta.action == PositionAction.UNKNOWN
    assert "flip_detected_as_unknown" in delta.reason
