"""[lot2 #79] hard price ceiling/floor : prix hors bornes dures -> refusé (référence aberrante)."""

import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE / "src"))

from hl_observer.quoting.hard_price_ceiling_floor import admissible   # noqa: E402


def test_dans_les_bornes():
    assert admissible(100.0, plancher=90.0, plafond=110.0)["admissible"] is True


def test_hors_bornes():
    r = admissible(200.0, plancher=90.0, plafond=110.0)
    assert r["admissible"] is False and r["raison"] == "PRIX_HORS_BORNES_DURES"


def test_bornes_incoherentes_ou_invalides():
    assert admissible(100.0, plancher=110.0, plafond=90.0)["admissible"] is False
    assert admissible(100.0, plancher=None, plafond=110.0)["admissible"] is False
