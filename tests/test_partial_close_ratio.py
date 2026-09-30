"""[pépite 290] partial-close ratio : répliquer le % d'exposition retiré, pas la quantité absolue du leader."""

import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE / "src"))

from hl_observer.copy_vault.partial_close_ratio import ratio_fermeture   # noqa: E402


def test_pourcentage_retire():
    r = ratio_fermeture(qte_reduite=3.0, position_avant=10.0)   # 30%
    assert r["pct"] == 0.3


def test_applique_a_notre_position():
    r = ratio_fermeture(qte_reduite=3.0, position_avant=10.0, notre_position=2.0)
    assert r["notre_reduction"] == 0.6                          # 30% de 2.0


def test_position_invalide():
    assert ratio_fermeture(1.0, 0.0)["pct"] == "UNMEASURABLE"
