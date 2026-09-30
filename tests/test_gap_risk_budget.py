"""[ARB #43] gap-risk budget : déplacement max tolérable pendant le délai entre jambes."""

import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE / "src"))

from hl_observer.arbitrage.gap_risk_budget import budget_bps, depasse_budget   # noqa: E402


def test_budget_fraction_de_ledge():
    assert budget_bps(40.0, fraction_tolerable=0.5) == 20.0
    assert budget_bps(0.0) == "UNMEASURABLE"                          # pas d'edge = pas de budget


def test_depassement():
    assert depasse_budget(25.0, 40.0, fraction_tolerable=0.5)["depasse"] is True   # 25 > 20
    assert depasse_budget(10.0, 40.0, fraction_tolerable=0.5)["depasse"] is False


def test_non_chiffrable_fail_closed():
    r = depasse_budget(None, 40.0)
    assert r["depasse"] is True and r["raison"] == "NON_CHIFFRABLE_FAIL_CLOSED"
