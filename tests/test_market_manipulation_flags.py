from hl_observer.risk.market_manipulation_flags import detect_market_manipulation_flags


def test_market_manipulation_flags_detects_multiple_risks():
    result = detect_market_manipulation_flags(spread_bps=50, volatility_bps=120, same_wallet_ratio=0.9, cancel_rate=0.9)
    assert result.suspicious is True
    assert result.risk_score == 1.0
