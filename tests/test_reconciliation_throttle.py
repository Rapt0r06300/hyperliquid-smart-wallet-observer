"""[ALL lot2 #27] throttle réconciliation : intervalle minimum entre queries pour éviter la tempête REST."""

import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE / "src"))

from hl_observer.api_governance.reconciliation_throttle import ThrottleReconciliation   # noqa: E402


def test_throttle_intervalle():
    t = ThrottleReconciliation(intervalle_min_ms=1000.0)
    assert t.peut_query("HL", now_ms=0.0)["ok"] is True
    t.marquer("HL", now_ms=0.0)
    assert t.peut_query("HL", now_ms=500.0)["ok"] is False   # trop tôt
    assert t.peut_query("HL", now_ms=1500.0)["ok"] is True   # intervalle écoulé


def test_cles_independantes():
    t = ThrottleReconciliation(intervalle_min_ms=1000.0)
    t.marquer("HL", now_ms=0.0)
    assert t.peut_query("BINANCE", now_ms=100.0)["ok"] is True


def test_temps_invalide():
    assert ThrottleReconciliation().peut_query("HL", now_ms=None)["ok"] is False
