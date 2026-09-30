"""[ARB #32] proportional residual hedge : un fill de 37 % -> 37 % de couverture, ni 0 ni 100 %."""

import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE / "src"))

from hl_observer.arbitrage.proportional_residual_hedge import couverture_proportionnelle   # noqa: E402


def test_fraction_exacte():
    r = couverture_proportionnelle(0.37, 1.0)
    assert r["fraction_remplie"] == 0.37
    assert r["qte_couverture"] == 0.37 and r["qte_residuelle"] == 0.63
    assert r["pleinement_couvert"] is False


def test_plein_fill():
    r = couverture_proportionnelle(1.0, 1.0)
    assert r["pleinement_couvert"] is True and r["qte_residuelle"] == 0.0


def test_quantites_invalides():
    assert couverture_proportionnelle(0.5, 0.0)["qte_couverture"] == "UNMEASURABLE"
