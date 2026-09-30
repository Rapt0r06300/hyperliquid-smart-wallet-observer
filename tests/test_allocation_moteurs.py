"""ALLOCATION DYNAMIQUE MULTI-MOTEURS (tâche 65, 23/07). Le cœur testé = la PORTE DE PREUVE : le
capital ne va QU'à un edge net PROUVÉ OOS-live ET qui BAT HLP. Un edge prometteur mais extrapolé, ou
positif mais dominé par HLP, reçoit ZÉRO. Aucun éligible -> tout en réserve (l'état honnête au 23/07).
"""
from __future__ import annotations

from hl_observer.funding.allocation_moteurs import (
    MoteurEtat, allouer_capital, etats_courants, rapport, HLP_APR_MIN)


def test_un_edge_PROMETTEUR_mais_non_prouve_OOS_recoit_ZERO():
    """Le cas cross-venue au 23/07 : 20 %/an mais net EXTRAPOLÉ (pas OOS live) -> exclu."""
    m = MoteurEtat("cross_venue", edge_net_apr_pct=20.0, prouve_oos=False)
    r = allouer_capital([m], capital_usd=1000.0)
    assert r["allocation"] == {} and r["reserve_usd"] == 1000.0
    assert r["exclus"]["cross_venue"] == "NON_PROUVE_OOS_LIVE"


def test_un_edge_POSITIF_mais_sous_HLP_est_DOMINE_donc_ZERO():
    """Le carry ~5 %/an : positif, prouvé, mais < HLP 15 % -> dominé -> exclu (positif ne suffit pas)."""
    m = MoteurEtat("carry", edge_net_apr_pct=5.0, prouve_oos=True)
    r = allouer_capital([m], capital_usd=1000.0)
    assert r["allocation"] == {} and r["exclus"]["carry"] == "DOMINE_PAR_HLP"


def test_aucun_eligible_TOUT_en_reserve():
    r = allouer_capital(etats_courants(), capital_usd=1000.0)
    assert r["allocation"] == {} and r["reserve_usd"] == 1000.0     # l'état honnête au 23/07


def test_un_edge_PROUVE_et_au_dessus_de_HLP_recoit_du_capital_reserve_conservee():
    m = MoteurEtat("cross_venue", edge_net_apr_pct=25.0, prouve_oos=True, qualite_data=0.9,
                   capacite_usd=1e9)
    r = allouer_capital([m], capital_usd=1000.0, reserve_frac=0.20, plafond_par_moteur=0.40)
    assert r["allocation"]["cross_venue"] > 0
    assert r["allocation"]["cross_venue"] <= 400.0 + 1e-6           # plafond 40 % du déployable
    assert r["reserve_usd"] >= 200.0                                # réserve 20 % conservée


def test_la_capacite_borne_l_allocation_mid_caps_ne_scalent_pas():
    m = MoteurEtat("cross_venue", edge_net_apr_pct=30.0, prouve_oos=True, qualite_data=0.9,
                   capacite_usd=120.0)                              # capacité minuscule
    r = allouer_capital([m], capital_usd=10000.0)
    assert r["allocation"]["cross_venue"] == 120.0                  # borné par la capacité, pas le %


def test_deux_eligibles_repartis_par_edge_ajuste_du_risque():
    a = MoteurEtat("A", edge_net_apr_pct=30.0, prouve_oos=True, qualite_data=0.9, drawdown_max_pct=0.0)
    b = MoteurEtat("B", edge_net_apr_pct=30.0, prouve_oos=True, qualite_data=0.9, drawdown_max_pct=100.0)
    r = allouer_capital([a, b], capital_usd=1000.0, plafond_par_moteur=1.0)
    assert r["allocation"]["A"] > r["allocation"]["B"]             # même APR, mais B a 2× le drawdown


def test_rapport_sur_l_etat_reel_est_tout_en_reserve():
    r = rapport(1000.0)
    assert r["moteurs_eligibles"] == [] and r["allocation"] == {}
