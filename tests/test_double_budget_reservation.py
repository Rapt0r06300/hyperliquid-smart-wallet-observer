"""[ARB #14] double budget reservation : A+B+frais réservés d'un bloc, sinon épisode refusé."""

import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE / "src"))

from hl_observer.arbitrage.double_budget_reservation import ReservationBudget   # noqa: E402


def test_reserve_atomique_et_disponible():
    rb = ReservationBudget(1000.0)
    r = rb.reserver_episode("ep1", capital_a=300.0, capital_b=300.0, frais=5.0)
    assert r["ok"] is True and r["reserve"] == 605.0
    assert rb.disponible() == 395.0


def test_refuse_si_ne_tient_pas_dun_bloc():
    rb = ReservationBudget(500.0)
    r = rb.reserver_episode("ep1", capital_a=300.0, capital_b=300.0, frais=5.0)
    assert r["ok"] is False and r["raison"] == "BUDGET_INSUFFISANT"
    assert rb.disponible() == 500.0                              # rien réservé


def test_liberation_rend_le_capital():
    rb = ReservationBudget(1000.0)
    rb.reserver_episode("ep1", capital_a=300.0, capital_b=300.0, frais=5.0)
    assert rb.liberer("ep1") is True
    assert rb.disponible() == 1000.0
