from hl_observer.arbitrage.basis_funding_model import estimate_basis_funding_edge


def test_basis_funding_edge_subtracts_costs():
    edge = estimate_basis_funding_edge(perp_price=101, spot_price=100, funding_bps_8h=8, hold_hours=8, cost_bps=20)
    assert edge.basis_bps == 100
    assert edge.net_edge_bps == 88
