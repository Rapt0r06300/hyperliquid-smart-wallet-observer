"""Contrat de l'estimateur d'edge funding (échelle commune pour le board)."""

from __future__ import annotations

from hl_observer.funding.funding_edge import (
    funding_net_edge_bps,
    funding_opportunity_edge,
    funding_receive_side,
)


def test_net_edge_is_accrual_minus_costs():
    # 2.5 bps/h × 8h = 20 bps brut − 6 coûts = 14 net
    assert funding_net_edge_bps(rate_bps_per_hour=2.5, holding_hours=8.0, round_trip_cost_bps=6.0) == 14.0
    # taux faible ne couvre pas les coûts -> net négatif (honnête)
    assert funding_net_edge_bps(rate_bps_per_hour=0.2, holding_hours=8.0, round_trip_cost_bps=6.0) < 0


def test_receive_side_follows_sign():
    assert funding_receive_side(2.0) == "SHORT"    # taux + -> encaisse en SHORT
    assert funding_receive_side(-2.0) == "LONG"
    assert funding_receive_side(0.0) == "NEUTRAL"


def test_opportunity_edge_gate_and_apr():
    good = funding_opportunity_edge(rate_bps_per_hour=2.5, holding_hours=8.0)
    assert good["tradeable"] is True and good["net_edge_bps"] == 14.0 and good["side"] == "SHORT"
    assert good["apr_pct"] == 219.0                # cohérent avec apr_rotation (2.5 bps/h)
    # coûts > accrual -> non tradeable
    weak = funding_opportunity_edge(rate_bps_per_hour=0.3, holding_hours=8.0, round_trip_cost_bps=6.0)
    assert weak["tradeable"] is False
    # APR gate: edge net positif mais APR sous le seuil -> refusé
    gated = funding_opportunity_edge(rate_bps_per_hour=2.5, holding_hours=8.0, min_apr_pct=300.0)
    assert gated["tradeable"] is False             # 219% < 300% requis


def test_negative_rate_also_tradeable_on_long_side():
    r = funding_opportunity_edge(rate_bps_per_hour=-2.5, holding_hours=8.0)
    assert r["tradeable"] is True and r["side"] == "LONG" and r["net_edge_bps"] == 14.0
