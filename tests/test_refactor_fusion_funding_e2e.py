from hl_observer.funding.funding_history_window import funding_window_stats
from hl_observer.funding.funding_rate_scanner import scan_funding_rates
from hl_observer.funding.spike_detector import detect_funding_spike


def test_funding_e2e_detects_spike_as_paper_signal_only() -> None:
    rows = [{"coin": "HYPE", "rates": [0.0, 0.0, 0.0, 0.0, 0.001]}]

    signals = scan_funding_rates(rows, sigma=2.0)

    assert len(signals) == 1
    assert signals[0].coin == "HYPE"
    assert signals[0].decision == "FUNDING_SPIKE"
    assert signals[0].z_score is not None


def test_funding_e2e_flat_history_is_no_trade() -> None:
    stats = funding_window_stats([0.0001, 0.0001, 0.0001, 0.0001])
    decision = detect_funding_spike([0.0001, 0.0001, 0.0001, 0.0001], sigma=2.0)

    assert stats.count == 4
    assert decision.spike is False
    assert decision.reason in {"INSUFFICIENT_VARIANCE", "INSUFFICIENT_HISTORY", "FUNDING_HISTORY_INSUFFICIENT"}
