"""[DATA lot2 #30] periodic book re-snapshot : re-snapshot même sans gap pour effacer la dérive cumulative."""

import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE / "src"))

from hl_observer.feed_integrity.periodic_book_resnapshot import doit_resnapshot   # noqa: E402


def test_intervalle_ecoule():
    r = doit_resnapshot(1000.0, 7000.0, intervalle_ms=5000.0)
    assert r["resnapshot"] is True and r["raison"] == "INTERVALLE_ECOULE"


def test_dans_intervalle():
    r = doit_resnapshot(1000.0, 3000.0, intervalle_ms=5000.0)
    assert r["resnapshot"] is False and r["reste_ms"] == 3000.0


def test_horodatage_inconnu():
    assert doit_resnapshot(None, 7000.0, intervalle_ms=5000.0)["resnapshot"] is True
