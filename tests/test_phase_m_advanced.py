"""M1/M2/M4/M6/M7/M10 — leviers avancés (pur / paper / read-only)."""

from hl_observer.edge.advanced_costs import carry_cost_bps, funding_accrued_bps, market_impact_bps
from hl_observer.signals.advanced_entry import dca_ladder, leader_drawdown_stop, session_allows


# M2 — impact vs ADV
def test_market_impact():
    assert market_impact_bps(0, 1000) == 0.0
    # taille = ADV -> coeff*sqrt(1) = 10 bps
    assert market_impact_bps(1000, 1000, coeff=10.0) == 10.0
    # taille 4x ADV -> 10*2 = 20 bps
    assert market_impact_bps(4000, 1000, coeff=10.0) == 20.0


# M4 — funding continu
def test_funding_accrued_continuous():
    # long, funding +0.01/h, 1800s = 0.5h -> 0.005*10000 = 50 bps payés
    assert funding_accrued_bps(0.01, 1800, "long") == 50.0
    # short avec funding positif -> reçoit (négatif = crédit)
    assert funding_accrued_bps(0.01, 1800, "short") == -50.0


# M10 — coût de portage
def test_carry_cost():
    assert carry_cost_bps(0.001, 10) == 100.0
    assert carry_cost_bps(-0.001, 10) == 0.0   # jamais négatif


# M1 — DCA ladder
def test_dca_ladder():
    lad = dca_ladder(300.0, 3, 20.0)
    assert len(lad) == 3
    assert lad[0] == (0.0, 100.0) and lad[2] == (40.0, 100.0)
    assert dca_ladder(100.0, 0, 10.0) == []


# M6 — stop-follow leader drawdown
def test_leader_drawdown_stop():
    assert leader_drawdown_stop(20.0, max_leader_dd_pct=15.0) is True
    assert leader_drawdown_stop(5.0, max_leader_dd_pct=15.0) is False


# M7 — filtre session
def test_session_filter():
    assert session_allows(14, blocked_hours=(2, 3, 4)) is True
    assert session_allows(3, blocked_hours=(2, 3, 4)) is False
