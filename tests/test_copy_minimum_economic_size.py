"""[pépite 296] copy minimum-economic-size : plus petite taille où l'edge leader > nos coûts fixes/spread/slippage."""

import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE / "src"))

from hl_observer.copy_vault.copy_minimum_economic_size import taille_minimale_economique   # noqa: E402


def test_taille_min_calculee():
    # marge = 30 - 5 - 5 = 20 bps = 0.002 ; cout_fixe 2 -> notional_min = 1000 ; prix 100 -> qty 10
    r = taille_minimale_economique(30.0, cout_fixe=2.0, spread_bps=5.0, slippage_bps=5.0, prix=100.0)
    assert r["notional_min"] == 1000.0 and r["qty_min"] == 10.0


def test_edge_ne_couvre_pas_couts_variables():
    r = taille_minimale_economique(5.0, cout_fixe=2.0, spread_bps=5.0, slippage_bps=5.0)   # marge -5
    assert r["notional_min"] == "AUCUNE_TAILLE_RENTABLE"


def test_entree_invalide():
    assert taille_minimale_economique(30.0, cout_fixe=-1.0, spread_bps=5.0,
                                      slippage_bps=5.0)["notional_min"] == "UNMEASURABLE"
