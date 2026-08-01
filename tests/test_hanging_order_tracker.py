"""[CROSS-VENUE lot2 #75] hanging-order tracker : garder une quote partielle encore rentable au lieu de cancel."""

import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE / "src"))

from hl_observer.order_lifecycle.hanging_order_tracker import TrackerHanging, GARDER, ANNULER   # noqa: E402


def test_garder_si_encore_rentable():
    t = TrackerHanging(seuil_edge_bps=5.0)
    t.enregistrer("o1", reste_qte=0.5)
    r = t.evaluer("o1", edge_courant_bps=8.0)
    assert r["decision"] == GARDER and r["raison"] == "ENCORE_RENTABLE"


def test_annuler_sous_seuil():
    t = TrackerHanging(seuil_edge_bps=5.0)
    t.enregistrer("o1", reste_qte=0.5)
    assert t.evaluer("o1", edge_courant_bps=2.0)["decision"] == ANNULER


def test_edge_non_mesurable_annule():
    t = TrackerHanging()
    t.enregistrer("o1", reste_qte=0.5)
    assert t.evaluer("o1", edge_courant_bps=None)["decision"] == ANNULER
