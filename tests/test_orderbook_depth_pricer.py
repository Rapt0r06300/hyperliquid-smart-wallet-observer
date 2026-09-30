from hl_observer.arbitrage.orderbook_depth_pricer import price_from_depth


def test_orderbook_depth_pricer_marks_partial():
    result = price_from_depth([{"price": 100, "size": 0.5}], target_notional_usdt=100)
    assert result.average_price == 100
    assert result.partial is True
