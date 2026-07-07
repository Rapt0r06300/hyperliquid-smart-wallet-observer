from hl_observer.funding.spike_detector import detect_funding_spike


def test_funding_spike_detector_two_sigma():
    decision = detect_funding_spike([0, 0, 0, 0, 0.1], sigma=2.0)
    assert decision.spike is True
    assert decision.reason == "FUNDING_SPIKE"
