"""[lot2 #100] account-equity MaxDrawdown + cooldown : couper si drawdown > seuil, cooldown avant reprise."""

import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE / "src"))

from hl_observer.risk_gates.account_equity_max_drawdown import MaxDrawdownCooldown, RUNNING, HALTED   # noqa: E402


def test_running_sous_seuil():
    m = MaxDrawdownCooldown(seuil_drawdown_pct=10.0, cooldown_ms=1000.0)
    m.evaluer(10000.0, now_ms=0.0)                        # pic
    assert m.evaluer(9500.0, now_ms=100.0)["etat"] == RUNNING   # -5%


def test_halted_au_dela_du_seuil():
    m = MaxDrawdownCooldown(seuil_drawdown_pct=10.0, cooldown_ms=1000.0)
    m.evaluer(10000.0, now_ms=0.0)
    r = m.evaluer(8500.0, now_ms=100.0)                   # -15%
    assert r["etat"] == HALTED and r["raison"] == "MAX_DRAWDOWN_DEPASSE"


def test_cooldown_puis_reprise():
    m = MaxDrawdownCooldown(seuil_drawdown_pct=10.0, cooldown_ms=1000.0)
    m.evaluer(10000.0, now_ms=0.0)
    m.evaluer(8500.0, now_ms=100.0)                       # halt jusqu'a 1100
    assert m.evaluer(9800.0, now_ms=500.0)["etat"] == HALTED       # en cooldown
    assert m.evaluer(9800.0, now_ms=2000.0)["etat"] == RUNNING     # recover apres cooldown (-2%)
