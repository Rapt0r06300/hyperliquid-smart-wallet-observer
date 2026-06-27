import pytest

from hyper_smart_observer.paper_trading.spread import apply_spread


def test_hypersmart_apply_spread_buy():
    assert apply_spread(100.0, "BUY", 2.0) == 100.01


def test_hypersmart_apply_spread_sell():
    assert apply_spread(100.0, "SELL", 2.0) == 99.99


def test_hypersmart_apply_spread_refuses_invalid_price():
    with pytest.raises(ValueError):
        apply_spread(0.0, "BUY", 2.0)


def test_hypersmart_apply_spread_refuses_negative_spread():
    with pytest.raises(ValueError):
        apply_spread(100.0, "BUY", -1.0)
