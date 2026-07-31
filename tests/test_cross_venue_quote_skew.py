"""[CROSS-VENUE #4] maximum quote skew : abs(ts_A − ts_B) > limite -> opportunité invalide."""

import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE / "src"))

from hl_observer.arbitrage.cross_venue_quote_skew import skew_acceptable   # noqa: E402


def test_skew_dans_la_limite_ok():
    r = skew_acceptable(1000, 1030, max_skew_ms=50)
    assert r["ok"] is True and r["skew_ms"] == 30.0


def test_skew_trop_grand_rejete():
    r = skew_acceptable(1000, 1200, max_skew_ms=50)
    assert r["ok"] is False and r["skew_ms"] == 200.0 and r["raison"] == "SKEW_TROP_GRAND"


def test_ts_manquant_non_mesurable():
    r = skew_acceptable(1000, None, max_skew_ms=50)
    assert r["ok"] is False and r["raison"] == "TS_NON_MESURABLE"
