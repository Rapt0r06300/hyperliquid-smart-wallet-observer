"""[ARB #24] tick-based repricing tolerance : ne replacer que si le prix cible bouge d'au moins X ticks."""

import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE / "src"))

from hl_observer.arbitrage.repricing_tolerance import doit_repricer   # noqa: E402


def test_sous_la_tolerance_on_garde():
    r = doit_repricer(100.00, 100.005, tick=0.01, min_ticks=1.0)
    assert r["repricer"] is False and r["raison"] == "SOUS_LA_TOLERANCE"


def test_mouvement_significatif_repricer():
    r = doit_repricer(100.00, 100.03, tick=0.01, min_ticks=1.0)
    assert r["repricer"] is True and r["delta_ticks"] == 3.0


def test_non_mesurable():
    r = doit_repricer("x", 100.0, tick=0.01)
    assert r["repricer"] is False and r["raison"] == "NON_MESURABLE"
