"""X1/X4 — INVARIANT : la porte de décision v12 DOIT importer ET appeler le pipeline de filtres
(anti-régression : le câblage ne doit jamais disparaître silencieusement). + comportement du
helper _appliquer_gardes : refuse une ENTRÉE périmée (fraîcheur), ne touche JAMAIS une SORTIE."""
from __future__ import annotations

import ast
from pathlib import Path
from types import SimpleNamespace

from hl_observer.edge.edge_net_v12 import EdgeNetV12Estimate
from hl_observer.pipeline.v12_decision_pipeline import _appliquer_gardes, V12DecisionPipelineConfig

PORTE = Path(__file__).resolve().parents[1] / "src" / "hl_observer" / "pipeline" / "v12_decision_pipeline.py"


def test_invariant_porte_importe_et_appelle_les_filtres():
    src = PORTE.read_text(encoding="utf-8")
    tree = ast.parse(src)
    importe = any(
        isinstance(n, ast.ImportFrom) and n.module and "filter_pipeline" in n.module
        for n in ast.walk(tree)
    )
    appels = {
        n.func.id for n in ast.walk(tree)
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)
    }
    assert importe, "la porte v12 doit importer filter_pipeline"
    assert "appliquer_filtres" in appels, "la porte doit APPELER appliquer_filtres"
    assert "_appliquer_gardes" in appels, "run_v12_decision_pipeline doit appeler _appliquer_gardes"


def _edge(net: float = 50.0) -> EdgeNetV12Estimate:
    return EdgeNetV12Estimate(measurable=True, accepted=True, gross_edge_bps=net,
                              total_cost_bps=0.0, net_edge_bps=net, threshold_bps=30.0)


def test_entree_perimee_degrade_edge_sous_plancher():
    edge = _edge(50.0)
    delta = SimpleNamespace(is_exit_or_reduce=False, coin="BTC", reason_codes=(), delta_id="d1")
    pin = SimpleNamespace(market_mids={"BTC": 100.0, "ETH": 50.0},
                          observed_at_ms=10_000_000, source_ts_ms=10_000_000 - 600_000,  # 600 s
                          wallet="0xabc")
    out = _appliquer_gardes(edge, delta, 100.0, pin, V12DecisionPipelineConfig())
    assert out.accepted is False
    assert "SIGNAL_TROP_VIEUX" in out.reason_codes
    assert out.net_edge_bps < 30.0                       # sous le plancher -> NO_TRADE


def test_sortie_jamais_degradee():
    edge = _edge(50.0)
    delta = SimpleNamespace(is_exit_or_reduce=True, coin="BTC", reason_codes=(), delta_id="d2")
    pin = SimpleNamespace(market_mids={"BTC": 100.0}, observed_at_ms=10_000_000,
                          source_ts_ms=1, wallet="0xabc")  # très vieux, mais SORTIE
    out = _appliquer_gardes(edge, delta, 100.0, pin, V12DecisionPipelineConfig())
    assert out is edge                                    # sortie non filtrée


def test_entree_fraiche_et_propre_passe_intacte():
    edge = _edge(50.0)
    delta = SimpleNamespace(is_exit_or_reduce=False, coin="BTC", reason_codes=(), delta_id="d3")
    pin = SimpleNamespace(market_mids={"BTC": 100.0, "ETH": 50.0},
                          observed_at_ms=10_000_000, source_ts_ms=10_000_000 - 10_000,  # 10 s
                          wallet="0xabc")
    out = _appliquer_gardes(edge, delta, 100.0, pin, V12DecisionPipelineConfig())
    assert out is edge                                    # rien ne refuse -> edge inchangé
