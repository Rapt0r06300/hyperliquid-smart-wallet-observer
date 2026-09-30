"""V2 + V3 : le moteur d'edge LIVE (edge_net_v12) ne fait JAMAIS fail-open.

Invariant permanent contre la maladie deja vecue (« plancher a zero », « frais 0.0 ») : un plancher
reel, des couts core REQUIS (None -> NO_TRADE), des defauts de config NON nuls, et jamais d'edge
accepte a net <= 0. Le moteur vivant est edge_net_v12 (PAS compute_net_edge, orphelin — cf. audit/cablage).
"""
from __future__ import annotations

import pytest

from hl_observer.edge.edge_net_v12 import EdgeNetV12Inputs, estimate_edge_net_v12
from hl_observer.pipeline.v12_decision_pipeline import V12DecisionPipelineConfig


def _inp(**kw):
    d = dict(leader_reference_price=100.0, current_mid=100.0, leader_expected_edge_bps=50.0,
             spread_bps=2.0, slippage_bps=2.0, fee_bps=4.5, funding_estimate_bps=0.0, min_edge_bps=30.0)
    d.update(kw)
    return EdgeNetV12Inputs(**d)


def test_v2_plancher_est_un_vrai_seuil_pas_zero():
    assert EdgeNetV12Inputs.__dataclass_fields__["min_edge_bps"].default >= 30.0


def test_v2_net_sous_le_plancher_est_refuse():
    e = estimate_edge_net_v12(_inp(leader_expected_edge_bps=20.0))   # net 20-8.5=11.5 < 30
    assert e.accepted is False and "EDGE_REMAINING_TOO_LOW" in e.reason_codes


def test_v3_cout_core_manquant_donne_no_trade():
    for champ in ("spread_bps", "slippage_bps", "fee_bps"):
        e = estimate_edge_net_v12(_inp(**{champ: None}))
        assert e.measurable is False and e.accepted is False, champ


def test_v3_defauts_de_cout_config_sont_non_nuls():
    cfg = V12DecisionPipelineConfig()
    assert (cfg.spread_bps or 0.0) > 0.0
    assert (cfg.slippage_bps or 0.0) > 0.0
    assert (cfg.fee_bps or 0.0) > 0.0


def test_v3_les_couts_sont_reellement_soustraits():
    e = estimate_edge_net_v12(_inp(leader_expected_edge_bps=50.0))
    assert e.total_cost_bps >= 8.5                                   # spread2+slippage2+fee4.5
    assert e.net_edge_bps == pytest.approx(50.0 - e.total_cost_bps)  # V5 : edge - couts, utilise


def test_v5_net_non_positif_jamais_accepte():
    e = estimate_edge_net_v12(_inp(leader_expected_edge_bps=5.0))    # 5 - 8.5 < 0
    assert e.accepted is False


def test_edge_sain_est_bien_accepte():
    e = estimate_edge_net_v12(_inp(leader_expected_edge_bps=60.0))   # 60-8.5=51.5 >= 30
    assert e.measurable is True and e.accepted is True
