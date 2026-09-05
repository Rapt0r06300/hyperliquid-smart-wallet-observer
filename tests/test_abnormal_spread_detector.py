from hl_observer.risk.abnormal_spread_detector import detect_abnormal_spread


def test_abnormal_spread_detector_blocks_wide_spread():
    result = detect_abnormal_spread(bid=100, ask=101, max_spread_bps=20)
    assert result.ok is False
    assert result.reason == "ABNORMAL_SPREAD"


def test_abnormal_spread_detector_allows_normal_spread():
    result = detect_abnormal_spread(bid=100.0, ask=100.05, max_spread_bps=12.0)
    assert result.ok is True
    assert result.reason is None
    assert 0.0 < result.spread_bps < 12.0
