"""[pépite 227] rounding-residual forecast : prévoir le delta après arrondi de chaque jambe."""

import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE / "src"))

from hl_observer.arbitrage.rounding_residual_forecast import prevoir   # noqa: E402


def test_residu_prevu():
    r = prevoir(1.0, lot_a=0.1, lot_b=0.15)               # A->1.0, B->0.9, residu 0.1
    assert abs(r["taille_a"] - 1.0) < 1e-9 and abs(r["taille_b"] - 0.9) < 1e-9
    assert abs(r["residu"] - 0.1) < 1e-9


def test_residu_nul():
    r = prevoir(0.6, lot_a=0.1, lot_b=0.1)
    assert r["residu"] == 0.0


def test_entree_invalide():
    assert prevoir(1.0, lot_a=0.0, lot_b=0.1)["residu"] == "UNMEASURABLE"
