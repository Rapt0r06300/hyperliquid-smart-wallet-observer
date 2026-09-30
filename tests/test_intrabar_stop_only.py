from hl_observer.backtesting.intrabar import SL, Bougie, resoudre_bougie


def test_long_stop_only_is_resolved_as_unambiguous_sl() -> None:
    candle = Bougie(open=100.0, high=103.0, low=94.0, close=99.0)
    result = resoudre_bougie(candle, sl=95.0, tp=108.0, long=True)

    assert result.issue == SL
    assert result.ambigu is False
