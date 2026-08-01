"""[ARB #31] filled-quantity hedge : la jambe opposée suit la quantité remplie, jamais la demandée."""

import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE / "src"))

from hl_observer.arbitrage.filled_quantity_hedge import taille_hedge   # noqa: E402


def test_hedge_sur_le_fill_reel():
    r = taille_hedge(0.37, qte_demandee=1.0)
    assert r["qte_hedge"] == 0.37 and r["sur_demande"] is False       # on hedge 0.37, pas 1.0


def test_borne_a_la_demande():
    r = taille_hedge(1.5, qte_demandee=1.0)
    assert r["qte_hedge"] == 1.0 and r["sur_demande"] is True         # jamais plus que demandé


def test_fill_inconnu_non_mesurable():
    assert taille_hedge(None)["qte_hedge"] == "UNMEASURABLE"
    assert taille_hedge(-1.0)["qte_hedge"] == "UNMEASURABLE"
