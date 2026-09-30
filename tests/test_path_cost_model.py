from hl_observer.arbitrage.path_cost_model import path_cost_bps
from hl_observer.arbitrage.path_fee_model import path_fee_bps


def test_path_cost_and_fee_models():
    cost = path_cost_bps(legs=3, fee_bps_per_leg=5, slippage_bps_per_leg=2, spread_bps_per_leg=1)
    assert cost.total_cost_bps == 24
    assert path_fee_bps(3, fee_bps_per_hop=5) == 15
