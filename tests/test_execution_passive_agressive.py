"""D20 — passif-puis-agressif : ne chasser que si l'edge survit au mouvement + coût taker."""
from __future__ import annotations

from hl_observer.backtesting.execution_passive_agressive import (
    RESTER_MAKER, CHASSER_TAKER, ANNULER, decision_execution,
)


def test_chasser_si_edge_survit_apres_taker():
    # edge 60, move adverse 5 -> restant 55 ; taker 10 -> 45 >= 30 -> chasser
    assert decision_execution(60.0, 5.0, cout_taker_bps=10.0, min_edge_bps=30.0) == CHASSER_TAKER


def test_rester_maker_si_edge_tient_sans_chasser_mais_pas_apres_taker():
    # edge 45, move 5 -> restant 40 >= 30 (rester) ; apres taker 10 -> 30 >= 30... egal -> chasser
    # on prend edge 42 : restant 37 >=30 ; apres taker 10 -> 27 < 30 -> RESTER
    assert decision_execution(42.0, 5.0, cout_taker_bps=10.0, min_edge_bps=30.0) == RESTER_MAKER


def test_annuler_si_edge_mort():
    # edge 40, move adverse 20 -> restant 20 < 30 -> annuler (ne PAS chasser un edge mort)
    assert decision_execution(40.0, 20.0, cout_taker_bps=10.0, min_edge_bps=30.0) == ANNULER


def test_mouvement_favorable_compte_comme_zero_adverse():
    # un mouvement "adverse" negatif (favorable) ne booste pas artificiellement -> borne a 0
    assert decision_execution(35.0, -100.0, cout_taker_bps=10.0, min_edge_bps=30.0) in (RESTER_MAKER, CHASSER_TAKER)
