from hl_observer.paper_trading.delta_neutral_position import build_delta_neutral_position


def test_delta_neutral_position_marks_balanced():
    position = build_delta_neutral_position(coin="HYPE", long_notional_usdt=100, short_notional_usdt=98, max_exposure_ratio=0.02)
    assert position.balanced is True
    assert position.net_exposure_usdt == 2
