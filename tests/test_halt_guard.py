"""[ARB lot2 #17] halt guard : pas d'arbitrage entre un marché actif et une venue haltée."""

import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE / "src"))

from hl_observer.order_lifecycle.halt_guard import peut_arbitrer   # noqa: E402


def test_deux_trading():
    assert peut_arbitrer("TRADING", "TRADING")["peut_arbitrer"] is True


def test_une_haltee_bloque():
    r = peut_arbitrer("TRADING", "HALTED")
    assert r["peut_arbitrer"] is False and "B" in r["venues_non_trading"]


def test_statut_inconnu_failclosed():
    assert peut_arbitrer("TRADING", "???")["peut_arbitrer"] is False
