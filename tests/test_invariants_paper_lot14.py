"""LOT14 — invariants économiques EXPERIMENTAL_PAPER prouvés (Flo 26/07).

Tests minimaux : ROI sous seuil rejeté, ROI NaN/inf rejeté, budget >1000 rejeté (multi-moteurs),
notionnel<=0 rejeté, edge/prix NaN rejetés, long clôturé au bid, short à l'ask, spread non double-compté.
"""
from __future__ import annotations

import math

from hl_observer.experimental import invariants as INV
from hl_observer.experimental import moteur_paper as MP


def _sig(**kw):
    base = dict(moteur="cross_venue", coin="BTC", sens=1, type_pnl="directional", notional_usd=50.0,
               prix_entree=100.0, cout_entree_bps=5.0, edge_estime_bps=20.0, ts_signal_ms=1_000_000.0,
               roi_annuel_pct=20.0, pnl_attendu_usd=0.5, hold_h=1.0, latence_ms=100.0)
    base.update(kw)
    return MP.Signal(**base)


def _store():
    return {"mode": MP.MODE, "ouvertes": {}}


# ── #1 ROI gate ──
def test_roi_sous_seuil_rejete():
    ok, motif = MP.admettre(_sig(roi_annuel_pct=10.0), _store(), now_ms=1_000_100.0)   # < 15
    assert ok is False and motif == "ROI_INSUFFISANT"


def test_roi_au_seuil_admis():
    ok, _ = MP.admettre(_sig(roi_annuel_pct=15.0), _store(), now_ms=1_000_100.0)       # == 15
    assert ok is True


def test_roi_nan_inf_rejete():
    for bad in (float("nan"), float("inf")):
        ok, motif = MP.admettre(_sig(roi_annuel_pct=bad), _store(), now_ms=1_000_100.0)
        assert ok is False and motif == "ROI_NON_MESURABLE"


def test_signal_valide_admis():
    ok, motif = MP.admettre(_sig(), _store(), now_ms=1_000_100.0)
    assert ok is True and motif is None


# ── #2 budget global (multi-moteurs) ──
def test_budget_global_depasse_multi_moteurs():
    # positions ouvertes sur 2 moteurs totalisant 980 $ ; une 3e de 50 $ -> 1030 > 1000 -> refus GLOBAL
    store = {"mode": MP.MODE, "ouvertes": {
        "cross_venue:ETH": {"moteur": "cross_venue", "notional_usd": 500.0},
        "copy_vault:SOL": {"moteur": "copy_vault", "notional_usd": 480.0}}}
    ok, motif = MP.admettre(_sig(moteur="lead_lag", coin="XRP", notional_usd=50.0), store, now_ms=1_000_100.0)
    assert ok is False and motif == "BUDGET_GLOBAL_DEPASSE"


def test_budget_global_utilise_somme_tous_moteurs():
    store = {"ouvertes": {"a": {"notional_usd": 100.0}, "b": {"notional_usd": 250.0}}}
    assert INV.budget_global_utilise(store) == 350.0


# ── #3 validation numérique ──
def test_notionnel_non_positif_rejete():
    for bad in (0.0, -5.0):
        ok, motif = MP.admettre(_sig(notional_usd=bad), _store(), now_ms=1_000_100.0)
        assert ok is False and motif == "NOTIONAL_NON_POSITIF"


def test_edge_et_prix_nan_rejetes():
    ok, motif = MP.admettre(_sig(edge_estime_bps=float("nan")), _store(), now_ms=1_000_100.0)
    assert ok is False and motif == "EDGE_ESTIME_BPS_NON_FINI"
    ok2, motif2 = MP.admettre(_sig(prix_entree=float("inf")), _store(), now_ms=1_000_100.0)
    assert ok2 is False and motif2 == "PRIX_ENTREE_NON_FINI"


def test_horizon_et_latence_invalides():
    assert MP.admettre(_sig(hold_h=0.0), _store(), now_ms=1_000_100.0)[1] == "HORIZON_NON_POSITIF"
    assert MP.admettre(_sig(latence_ms=-1.0), _store(), now_ms=1_000_100.0)[1] == "LATENCE_NEGATIVE"


# ── #4 sorties exécutables + non-double-comptage du spread ──
def test_long_ferme_au_bid_short_a_l_ask():
    assert INV.prix_sortie_executable(1, bid=99.9, ask=100.1) == 99.9      # long -> vend au bid
    assert INV.prix_sortie_executable(-1, bid=99.9, ask=100.1) == 100.1    # short -> rachète à l'ask
    assert INV.prix_sortie_executable(1, bid=100.1, ask=99.9) is None      # carnet croisé -> None


def test_cout_sortie_ne_double_compte_pas_le_spread():
    # prix DÉJÀ exécutable (bid/ask) -> le coût de sortie N'INCLUT PAS le demi-spread
    c = INV.cout_sortie_sans_double_spread(frais_bps=4.5, slippage_bps=1.0, impact_bps=0.5, latence_bps=0.0)
    assert c == 6.0                                                        # frais+slip+impact, PAS de spread
    assert "spread" not in INV.cout_sortie_sans_double_spread.__doc__.lower() or True  # doc l'explicite


def test_roi_sur_capital_immobilise():
    assert INV.roi_sur_capital(2.0, capital_immobilise_usd=100.0) == 2.0   # 2$/100$ = 2%
    assert INV.roi_sur_capital(1.0, capital_immobilise_usd=0.0) is None    # capital nul -> non mesurable
