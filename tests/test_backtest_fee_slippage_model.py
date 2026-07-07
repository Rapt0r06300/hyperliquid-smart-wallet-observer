from hl_observer.backtesting.fee_model import calculate_fee_usdt
from hl_observer.backtesting.slippage_model import apply_slippage
from hl_observer.backtesting.partial_fill_model import estimate_partial_fill_ratio
from hl_observer.backtesting.missed_fill_model import is_missed_fill


def test_fee_slippage_partial_and_missed_models():
    assert calculate_fee_usdt(1000, fee_bps=5) == 0.5
    assert apply_slippage(100, side="LONG", slippage_bps=10) > 100
    assert apply_slippage(100, side="SHORT", slippage_bps=10) < 100
    assert estimate_partial_fill_ratio(requested_notional_usdt=100, available_depth_usdt=25) == 0.25
    assert is_missed_fill(age_ms=10_001, max_age_ms=10_000, partial_ratio=1.0)
