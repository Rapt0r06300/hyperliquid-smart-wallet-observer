from hl_observer.arbitrage.triangular_graph import TriangularCycle
from hl_observer.arbitrage.triangular_opportunity_detector import detect_triangular_opportunities


def test_triangular_detector_rejects_positive_gross_when_costs_exceed_edge():
    rows = detect_triangular_opportunities([TriangularCycle(("A", "B", "C"), 1.001)], min_net_edge_bps=1, fee_bps_per_leg=5, slippage_bps_per_leg=1)
    assert rows[0].accepted is False
    assert rows[0].reason == "TRIANGULAR_EDGE_TOO_LOW"
