"""[lot2 #78] moving price bands : quote interdite hors de l'enveloppe autour du marché."""

import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE / "src"))

from hl_observer.quoting.moving_price_bands import dans_bande   # noqa: E402


def test_dans_la_bande():
    r = dans_bande(100.2, 100.0, demi_bande_bps=50.0)    # 20 bps
    assert r["autorisee"] is True


def test_hors_bande():
    r = dans_bande(101.0, 100.0, demi_bande_bps=50.0)    # 100 bps
    assert r["autorisee"] is False and r["raison"] == "HORS_BANDE"


def test_prix_invalide():
    assert dans_bande("x", 100.0)["autorisee"] is False
