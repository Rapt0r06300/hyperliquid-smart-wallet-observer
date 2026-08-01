"""[lot2 #80] order-refresh tolerance : ne pas perdre la queue pour un gain de prix négligeable."""

import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE / "src"))

from hl_observer.quoting.order_refresh_tolerance import doit_refresh   # noqa: E402


def test_sous_tolerance_garder_queue():
    r = doit_refresh(100.00, 100.005, tick=0.01, min_ticks=1.0)   # 0.5 tick
    assert r["refresh"] is False and r["raison"] == "SOUS_TOLERANCE_GARDER_QUEUE"


def test_gain_significatif_refresh():
    r = doit_refresh(100.00, 100.03, tick=0.01, min_ticks=1.0)
    assert r["refresh"] is True and r["gain_ticks"] == 3.0


def test_non_mesurable_hold():
    assert doit_refresh("x", 100.0, tick=0.01)["refresh"] is False
