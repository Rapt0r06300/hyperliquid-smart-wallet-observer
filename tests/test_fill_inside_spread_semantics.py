"""[lot2 #88] fill-inside-spread semantics : hypothèse de fill configurable, pessimiste par défaut."""

import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE / "src"))

from hl_observer.quoting.fill_inside_spread_semantics import remplit, PESSIMISTE, OPTIMISTE, AUCUN   # noqa: E402


def test_pessimiste_pas_de_fill_inside():
    # achat a 100.05 dans le spread [100, 100.1] -> pas de fill en pessimiste
    r = remplit(100.05, 100.0, 100.1, "ACHAT", mode=PESSIMISTE)
    assert r["rempli"] is False and r["raison"] == "INSIDE_SPREAD_PAS_DE_FILL"


def test_optimiste_fill_inside():
    r = remplit(100.05, 100.0, 100.1, "ACHAT", mode=OPTIMISTE)
    assert r["rempli"] is True


def test_croisement_remplit_et_aucun():
    assert remplit(100.1, 100.0, 100.1, "ACHAT", mode=PESSIMISTE)["rempli"] is True   # croise l'ask
    assert remplit(100.05, 100.0, 100.1, "ACHAT", mode=AUCUN)["rempli"] is False
