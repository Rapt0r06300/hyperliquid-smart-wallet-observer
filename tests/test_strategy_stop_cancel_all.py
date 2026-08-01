"""[lot2 #95] strategy stop = cancel-all : l'arrêt annule tous les child orders, aucun orphelin."""

import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE / "src"))

from hl_observer.execution_core.strategy_stop_cancel_all import GestionnaireChildOrders   # noqa: E402


def test_arret_annule_tout():
    g = GestionnaireChildOrders()
    g.enregistrer("strat1", "o1")
    g.enregistrer("strat1", "o2")
    r = g.arreter("strat1")
    assert set(r["a_annuler"]) == {"o1", "o2"} and r["aucun_orphelin"] is True
    assert g.actifs("strat1") == []


def test_autre_strategie_intacte():
    g = GestionnaireChildOrders()
    g.enregistrer("strat1", "o1")
    g.enregistrer("strat2", "o2")
    g.arreter("strat1")
    assert g.actifs("strat2") == ["o2"]


def test_retrait_unitaire():
    g = GestionnaireChildOrders()
    g.enregistrer("s", "o1")
    g.retirer("s", "o1")
    assert g.actifs("s") == []
