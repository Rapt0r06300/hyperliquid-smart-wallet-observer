import pytest

from hyper_smart_observer.paper_trading.slippage import apply_slippage


def test_hypersmart_apply_slippage_buy():
    assert apply_slippage(100.0, "BUY", 5.0) == 100.05


def test_hypersmart_apply_slippage_sell():
    assert apply_slippage(100.0, "SELL", 5.0) == 99.95


def test_hypersmart_apply_slippage_refuses_negative_slippage():
    with pytest.raises(ValueError):
        apply_slippage(100.0, "BUY", -1.0)


def test_hypersmart_apply_slippage_refuses_invalid_price():
    with pytest.raises(ValueError):
        apply_slippage(0.0, "SELL", 5.0)
