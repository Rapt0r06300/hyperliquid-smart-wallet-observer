from hl_observer.arbitrage.dual_venue_hedge_sim import simulate_dual_venue_hedge


def test_dual_venue_missing_leg_blocks():
    result = simulate_dual_venue_hedge(long_leg_price=100, short_leg_price=None, net_edge_bps=100)
    assert result.accepted is False
    assert result.reason == "MISSING_LEG"
    assert result.real_execution is False
