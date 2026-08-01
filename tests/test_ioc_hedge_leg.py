"""[ARB lot2 #5] IOC hedge leg : le reliquat est annulé, jamais laissé en ordre passif."""

import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE / "src"))

from hl_observer.order_lifecycle.ioc_hedge_leg import simuler_ioc   # noqa: E402


def test_fill_partiel_reliquat_annule():
    r = simuler_ioc(1.0, 0.6)
    assert r["remplie"] == 0.6 and r["reliquat_annule"] == 0.4 and r["reste_passif"] == 0.0


def test_fill_complet():
    r = simuler_ioc(1.0, 2.0)
    assert r["remplie"] == 1.0 and r["reliquat_annule"] == 0.0


def test_entree_invalide():
    assert simuler_ioc(-1.0, 0.6)["remplie"] == "UNMEASURABLE"
