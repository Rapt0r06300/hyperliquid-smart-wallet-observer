from hyper_smart_observer.scoring.drawdown import calculate_max_drawdown
from hyper_smart_observer.scoring.equity_curve import build_equity_curve_from_pnl


def test_hypersmart_equity_curve_from_pnl():
    assert build_equity_curve_from_pnl([2.0, -1.0, 3.0]) == [0.0, 2.0, 1.0, 4.0]


def test_hypersmart_max_drawdown():
    assert calculate_max_drawdown([0.0, 5.0, 2.0, 7.0, 6.0]) == 3.0


def test_hypersmart_max_drawdown_no_drawdown():
    assert calculate_max_drawdown([0.0, 1.0, 2.0]) == 0.0


def test_hypersmart_max_drawdown_empty_curve():
    assert calculate_max_drawdown([]) is None
