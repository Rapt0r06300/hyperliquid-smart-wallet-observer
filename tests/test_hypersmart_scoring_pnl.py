from hyper_smart_observer.scoring.pnl import (
    calculate_gross_pnl,
    calculate_net_pnl_after_fees,
    calculate_total_fees,
)
from hyper_smart_observer.scoring.risk_metrics import calculate_profit_factor, safe_divide
from hyper_smart_observer.scoring.winrate import (
    calculate_average_loss,
    calculate_average_win,
    calculate_winrate,
)


def test_hypersmart_safe_divide():
    assert safe_divide(6, 3) == 2
    assert safe_divide(1, 0) is None
    assert safe_divide(1, 0, default=0) == 0


def test_hypersmart_winrate_simple_ignores_neutral():
    assert calculate_winrate([2.0, -1.0, 0.0, 3.0]) == 2 / 3


def test_hypersmart_winrate_without_data():
    assert calculate_winrate([]) is None
    assert calculate_winrate([0.0]) is None


def test_hypersmart_average_win_loss():
    values = [10.0, -4.0, 2.0, -2.0]
    assert calculate_average_win(values) == 6.0
    assert calculate_average_loss(values) == -3.0


def test_hypersmart_profit_factor_normal_and_without_losses():
    assert calculate_profit_factor(12.0, -3.0) == 4.0
    assert calculate_profit_factor(12.0, 0.0) is None


def test_hypersmart_net_pnl_after_fees():
    assert calculate_gross_pnl([3.0, -1.0]) == 2.0
    assert calculate_total_fees([0.1, 0.2]) == 0.30000000000000004
    assert calculate_net_pnl_after_fees([3.0, -1.0], [0.1, 0.2]) == 1.7
