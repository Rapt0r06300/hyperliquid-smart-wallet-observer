from hl_observer.risk.liquidity_cliff_detector import detect_liquidity_cliff


def test_liquidity_cliff_blocks_thin_near_depth():
    result = detect_liquidity_cliff([{"notional_usdt": 100}, {"notional_usdt": 100}], min_near_depth_usdt=1000)
    assert result.blocked is True
    assert result.reason == "LIQUIDITY_CLIFF"
