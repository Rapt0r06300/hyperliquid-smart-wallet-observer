"""[lot2 #84] buy/sell level structures asymétriques : profondeur indépendante par côté."""

import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE / "src"))

from hl_observer.quoting.asymmetric_level_structures import structurer   # noqa: E402


def test_asymetrie():
    r = structurer(niveaux_buy=[{"ecart_bps": 5, "taille": 1.0}, {"ecart_bps": 10, "taille": 2.0}],
                   niveaux_sell=[{"ecart_bps": 5, "taille": 1.0}])
    assert r["n_buy"] == 2 and r["n_sell"] == 1 and r["asymetrique"] is True


def test_symetrique():
    lv = [{"ecart_bps": 5, "taille": 1.0}]
    r = structurer(niveaux_buy=lv, niveaux_sell=lv)
    assert r["asymetrique"] is False


def test_niveau_invalide_ignore():
    r = structurer(niveaux_buy=[{"ecart_bps": 5, "taille": 0.0}], niveaux_sell=[])
    assert r["n_buy"] == 0
