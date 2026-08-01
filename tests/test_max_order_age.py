"""[lot2 #77] max_order_age : un ordre trop vieux expire même si son prix est encore acceptable."""

import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE / "src"))

from hl_observer.quoting.max_order_age import expire   # noqa: E402


def test_dans_lage():
    r = expire(1000.0, 3000.0, max_age_ms=5000.0)
    assert r["expire"] is False and r["reste_ms"] == 3000.0


def test_trop_vieux():
    r = expire(1000.0, 7000.0, max_age_ms=5000.0)
    assert r["expire"] is True and r["raison"] == "MAX_ORDER_AGE_ATTEINT"


def test_horodatage_inconnu():
    assert expire(None, 7000.0, max_age_ms=5000.0)["expire"] is True
