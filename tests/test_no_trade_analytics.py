from hl_observer.validation.no_trade_analyzer import no_trade_precision


def test_no_trade_precision_calculated():
    assert no_trade_precision(avoided_losses=7, rejected_count=10) == 0.7
