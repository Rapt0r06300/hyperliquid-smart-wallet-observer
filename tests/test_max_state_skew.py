"""[COPY-VAULT lot2 #63] maximum state skew : écart max fill_ts vs snapshot ; au-delà -> action non fiable."""

import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE / "src"))

from hl_observer.copy_vault.max_state_skew import fiable   # noqa: E402


def test_skew_acceptable():
    r = fiable(1000.0, 1500.0, skew_max_ms=2000.0)
    assert r["fiable"] is True and r["skew_ms"] == 500.0


def test_skew_trop_grand():
    r = fiable(1000.0, 5000.0, skew_max_ms=2000.0)
    assert r["fiable"] is False and r["raison"] == "SKEW_TROP_GRAND_ACTION_NON_FIABLE"


def test_horodatage_inconnu():
    assert fiable(None, 1500.0)["fiable"] is False
