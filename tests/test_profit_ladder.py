"""[ARB #18] profit ladder : chaque tranche ne s'active que si l'edge courant atteint SON edge cible."""

import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE / "src"))

from hl_observer.arbitrage.profit_ladder import ProfitLadder   # noqa: E402


def test_activation_par_palier():
    lad = ProfitLadder([(10.0, 100.0), (30.0, 200.0), (50.0, 300.0)])
    assert lad.taille_active(5.0) == 0.0                        # sous le premier palier
    assert lad.taille_active(10.0) == 100.0                     # 1er palier atteint
    assert lad.taille_active(35.0) == 300.0                     # 2 paliers (100+200)
    assert lad.taille_active(50.0) == 600.0                     # tout


def test_edge_non_mesurable_rien_actif():
    lad = ProfitLadder([(10.0, 100.0)])
    assert lad.ordres_actifs("NA") == []


def test_tranches_triees_par_cible():
    lad = ProfitLadder([(50.0, 300.0), (10.0, 100.0)])
    actifs = lad.ordres_actifs(10.0)
    assert actifs == [{"edge_cible_bps": 10.0, "taille": 100.0}]
