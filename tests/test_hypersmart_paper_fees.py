import pytest

from hyper_smart_observer.paper_trading.fees import calculate_fee


def test_hypersmart_calculate_fee_normal():
    assert calculate_fee(1000.0, 5.0) == 0.5


def test_hypersmart_calculate_fee_refuses_negative_notional():
    with pytest.raises(ValueError):
        calculate_fee(-1.0, 5.0)


def test_hypersmart_calculate_fee_refuses_negative_rate():
    with pytest.raises(ValueError):
        calculate_fee(100.0, -1.0)
