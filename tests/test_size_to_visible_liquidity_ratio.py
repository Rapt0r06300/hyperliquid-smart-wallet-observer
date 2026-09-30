"""[pépite 287] size-to-visible-liquidity ratio : taille du leader relative au carnet présent au fill."""

import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE / "src"))

from hl_observer.copy_vault.size_to_visible_liquidity_ratio import ratio   # noqa: E402


def test_petite_taille_pas_d_impact():
    r = ratio(taille=1.0, liquidite_visible=100.0, seuil_impact=0.1)   # 0.01 < 0.1
    assert r["ratio"] == 0.01 and r["impact_notable"] is False


def test_grosse_taille_impact():
    r = ratio(taille=30.0, liquidite_visible=100.0, seuil_impact=0.1)  # 0.3 >= 0.1
    assert r["impact_notable"] is True


def test_liquidite_invalide():
    assert ratio(1.0, 0.0)["ratio"] == "UNMEASURABLE"
