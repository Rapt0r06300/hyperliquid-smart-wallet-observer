from hl_observer.arbitrage.funding_adjusted_edge import funding_adjusted_edge_bps


def test_funding_adjusted_edge_rewards_short_when_funding_positive() -> None:
    edge = funding_adjusted_edge_bps(gross_edge_bps=20, funding_rate=0.001, side="SHORT")

    assert edge.funding_carry_bps == 10
    assert edge.adjusted_edge_bps == 30


def test_funding_adjusted_edge_penalizes_long_when_funding_positive() -> None:
    edge = funding_adjusted_edge_bps(gross_edge_bps=20, funding_rate=0.001, side="LONG")

    assert edge.funding_carry_bps == -10
    assert edge.adjusted_edge_bps == 10
