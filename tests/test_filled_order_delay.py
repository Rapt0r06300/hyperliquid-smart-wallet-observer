"""[CROSS-VENUE lot2 #74] filled-order delay : pas de recréation instantanée d'un ordre équivalent après un fill."""

import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE / "src"))

from hl_observer.order_lifecycle.filled_order_delay import peut_recreer   # noqa: E402


def test_delai_non_ecoule_bloque():
    r = peut_recreer(1000.0, 1500.0, delai_ms=1000.0)
    assert r["peut_recreer"] is False and r["raison"] == "DELAI_POST_FILL_NON_ECOULE"


def test_delai_ecoule_autorise():
    r = peut_recreer(1000.0, 2500.0, delai_ms=1000.0)
    assert r["peut_recreer"] is True


def test_horodatage_inconnu_bloque():
    assert peut_recreer(None, 2500.0)["peut_recreer"] is False
