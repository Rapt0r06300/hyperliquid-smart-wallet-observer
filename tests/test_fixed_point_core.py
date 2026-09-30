"""[pépite 220] fixed-point core : entiers scalés/Decimal, pas de dérive float."""

import sys
from pathlib import Path
from decimal import Decimal

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE / "src"))

from hl_observer.accounting.fixed_point_core import vers_unites, depuis_unites, somme_exacte   # noqa: E402


def test_conversion_entiere():
    assert vers_unites("1.23", scale=2) == 123
    assert depuis_unites(123, scale=2) == Decimal("1.23")


def test_somme_exacte_sans_derive():
    # 0.1 + 0.2 en float = 0.30000000000000004 ; en fixed-point c'est exactement 0.3
    assert somme_exacte(["0.1", "0.2"], scale=2) == Decimal("0.30")


def test_valeur_invalide():
    assert vers_unites(None, scale=2) == "UNMEASURABLE"
