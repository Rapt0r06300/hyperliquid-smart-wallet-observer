from hl_observer.risk.abnormal_spread_detector import detect_abnormal_spread


def test_abnormal_spread_detector_blocks_wide_spread():
    result = detect_abnormal_spread(bid=100, ask=101, max_spread_bps=20)
    assert result.ok is False
    assert result.reason == "ABNORMAL_SPREAD"
