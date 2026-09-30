"""X1/X2/X3/X4 — la porte de décision v12 branche les gardes ET le sizing.

INVARIANT (X4) : la porte DOIT importer + appeler le pipeline de filtres, l'état moteur et le
sizing (anti-régression : le câblage ne disparaît jamais en silence).
COMPORTEMENT : _appliquer_gardes refuse une ENTRÉE mauvaise (fraîcheur, wallet structurel,
stale-tick, réserve de marge, crowding) et ne touche JAMAIS une SORTIE ; _etat_moteur dérive
capital/marge/drawdown du moteur RÉEL ; _facteur_sizing réduit la taille en drawdown (X3)."""
from __future__ import annotations

import ast
from pathlib import Path
from types import SimpleNamespace

from hl_observer.edge.edge_net_v12 import EdgeNetV12Estimate
from hl_observer.pipeline.v12_decision_pipeline import (
    V12DecisionPipelineConfig, _appliquer_gardes, _etat_moteur, _facteur_sizing,
)

PORTE = Path(__file__).resolve().parents[1] / "src" / "hl_observer" / "pipeline" / "v12_decision_pipeline.py"


def test_invariant_porte_cable_filtres_etat_et_sizing():
    tree = ast.parse(PORTE.read_text(encoding="utf-8"))
    importe = any(isinstance(n, ast.ImportFrom) and n.module and "filter_pipeline" in n.module
                  for n in ast.walk(tree))
    appels = {n.func.id for n in ast.walk(tree) if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)}
    assert importe, "la porte doit importer filter_pipeline"
    for nom in ("appliquer_filtres", "_appliquer_gardes", "_etat_moteur", "_facteur_sizing"):
        assert nom in appels, f"la porte doit appeler {nom}"


def _edge(net: float = 50.0) -> EdgeNetV12Estimate:
    return EdgeNetV12Estimate(measurable=True, accepted=True, gross_edge_bps=net,
                              total_cost_bps=0.0, net_edge_bps=net, threshold_bps=30.0)


def _delta(coin="BTC", sortie=False):
    return SimpleNamespace(is_exit_or_reduce=sortie, coin=coin, reason_codes=(), delta_id="d")


def _pin(**kw):
    base = dict(market_mids={"BTC": 100.0, "ETH": 50.0}, observed_at_ms=10_000_000,
               source_ts_ms=10_000_000 - 10_000, wallet="0xabc",
               reference_mids={}, edge_history_by_coin={}, wallet_stats=None)
    base.update(kw)
    return SimpleNamespace(**base)


CFG = V12DecisionPipelineConfig()
ETAT_VIDE = {"capital": None, "marge_utilisee": None, "drawdown_frac": 0.0}


# ---- X1 : gate d'entrée / non-blocage des sorties ----

def test_entree_perimee_degrade_sous_plancher():
    out, ctx = _appliquer_gardes(_edge(50.0), _delta(), 100.0,
                                 _pin(source_ts_ms=10_000_000 - 600_000), CFG, ETAT_VIDE)
    assert out.accepted is False and "SIGNAL_TROP_VIEUX" in out.reason_codes
    assert out.net_edge_bps < 30.0
    assert "SIGNAL_TROP_VIEUX" in ctx["gardes_refus"]


def test_sortie_jamais_degradee():
    edge = _edge(50.0)
    out, ctx = _appliquer_gardes(edge, _delta(sortie=True), 100.0,
                                 _pin(source_ts_ms=1), CFG, ETAT_VIDE)
    assert out is edge and ctx.get("gardes_sortie") is True


def test_entree_fraiche_propre_passe_intacte():
    edge = _edge(50.0)
    out, _ = _appliquer_gardes(edge, _delta(), 100.0, _pin(), CFG, ETAT_VIDE)
    assert out is edge


# ---- X2 : gardes ACTIVÉS par les entrées plombées ----

def test_x2_wallet_structurel_refuse_via_porte():
    stats = {"adresse": "0xvault", "winrate": 1.0, "pnl_total_usd": 0.0, "n_trades": 5000}
    out, ctx = _appliquer_gardes(_edge(), _delta(), 100.0, _pin(wallet_stats=stats), CFG, ETAT_VIDE)
    assert out.accepted is False and "WALLET_STRUCTUREL" in ctx["gardes_refus"]


def test_x2_stale_tick_refuse_via_reference_mids():
    out, ctx = _appliquer_gardes(_edge(), _delta(), 130.0,
                                 _pin(reference_mids={"BTC": 100.0}), CFG, ETAT_VIDE)  # +30% > 15%
    assert out.accepted is False and "TICK_STALE" in ctx["gardes_refus"]


def test_x2_reserve_marge_refuse_via_etat_moteur():
    etat = {"capital": 1000.0, "marge_utilisee": 990.0, "drawdown_frac": 0.0}  # >80% déployé
    out, ctx = _appliquer_gardes(_edge(), _delta(), 100.0, _pin(), CFG, etat)
    assert out.accepted is False and "RESERVE_MARGE_VIOLEE" in ctx["gardes_refus"]


def test_x2_crowding_refuse_via_edge_history():
    out, ctx = _appliquer_gardes(_edge(), _delta(), 100.0,
                                 _pin(edge_history_by_coin={"BTC": {"hist": 40.0, "recent": 5.0}}),
                                 CFG, ETAT_VIDE)
    assert out.accepted is False and "EDGE_SATURE" in ctx["gardes_refus"]


# ---- X2 : _etat_moteur dérive l'état RÉEL du moteur ----

def _fake_engine(cash=1000.0, realized=0.0, hw=1000.0, leverage=10.0, cap=1200.0, notionals=()):
    cfg = SimpleNamespace(leverage=leverage, max_total_exposure_usdt=cap)
    positions = [SimpleNamespace(notional_usdt=n) for n in notionals]
    return SimpleNamespace(cash_usdt=cash, realized_pnl_usdt=realized,
                           _high_water_equity=hw, config=cfg, positions=positions)


def test_etat_moteur_capital_marge_drawdown():
    eng = _fake_engine(cash=800.0, realized=0.0, hw=1000.0, leverage=10.0, cap=1200.0,
                       notionals=(5000.0, 5000.0))   # marge = 10000/10 = 1000
    etat = _etat_moteur(eng)
    assert etat["capital"] == 1200.0
    assert abs(etat["marge_utilisee"] - 1000.0) < 1e-6
    assert abs(etat["drawdown_frac"] - 0.2) < 1e-6   # (1000-800)/1000


def test_etat_moteur_sans_positions_marge_zero_drawdown_zero():
    etat = _etat_moteur(_fake_engine(cash=1000.0, hw=1000.0, notionals=()))
    assert etat["marge_utilisee"] == 0.0 and etat["drawdown_frac"] == 0.0


# ---- X3 : sizing consommé (drawdown → taille réduite) ----

def test_x3_facteur_sizing_neutre_sans_drawdown():
    assert _facteur_sizing({"drawdown_frac": 0.0}) == 1.0


def test_x3_facteur_sizing_reduit_en_drawdown():
    plein = _facteur_sizing({"drawdown_frac": 0.0})
    moyen = _facteur_sizing({"drawdown_frac": 0.15})
    plancher = _facteur_sizing({"drawdown_frac": 0.30})
    assert plein == 1.0
    assert 0.2 <= moyen < 1.0                          # réduction progressive
    assert abs(plancher - 0.2) < 1e-9                  # plancher (taille_min)
    assert moyen < plein and plancher <= moyen


def test_x3_facteur_sizing_absent_neutre():
    assert _facteur_sizing({"drawdown_frac": None}) == 1.0
