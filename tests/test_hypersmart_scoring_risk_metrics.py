from hyper_smart_observer.scoring.risk_metrics import (
    calculate_calmar,
    calculate_sharpe,
    calculate_sortino,
)


def test_hypersmart_sharpe_with_zero_variance():
    assert calculate_sharpe([1.0, 1.0, 1.0]) is None


def test_hypersmart_sortino_without_downside():
    assert calculate_sortino([1.0, 2.0, 3.0]) is None


def test_hypersmart_calmar_with_zero_drawdown():
    assert calculate_calmar(10.0, 0.0) is None


def test_hypersmart_sharpe_with_variance():
    assert calculate_sharpe([1.0, -1.0, 2.0]) is not None
