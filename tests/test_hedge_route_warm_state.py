"""[pépite 236] hedge route warm-state : état frais sur la route secondaire, sinon froide."""

import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE / "src"))

from hl_observer.routing.hedge_route_warm_state import est_warm   # noqa: E402


def test_warm():
    assert est_warm(500.0, ttl_warm_ms=2000.0)["warm"] is True


def test_froide():
    r = est_warm(5000.0, ttl_warm_ms=2000.0)
    assert r["warm"] is False and r["raison"] == "ETAT_SECONDAIRE_FROID"


def test_age_inconnu():
    assert est_warm(None)["warm"] is False
