"""[pépite 273] critical overflow = fail closed : overflow file BBO/L2 → plus de trade jusqu'au resync."""

import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE / "src"))

from hl_observer.capture.critical_overflow_fail_closed import GardeOverflowCritique   # noqa: E402


def test_trade_autorise_au_depart():
    assert GardeOverflowCritique().trade_autorise()["autorise"] is True


def test_overflow_bloque_trade():
    g = GardeOverflowCritique()
    g.signaler_overflow("L2")
    r = g.trade_autorise()
    assert r["autorise"] is False and r["raison"] == "OVERFLOW_CRITIQUE_RESYNC_REQUIS"


def test_resync_reautorise():
    g = GardeOverflowCritique()
    g.signaler_overflow()
    g.resync()
    assert g.trade_autorise()["autorise"] is True
