"""ALPHA P33/P44/P45 — gates recherche : cost-aware, early-stop, multiple-testing."""

import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE / "src"))

from hl_observer.research import validation_gates as G  # noqa: E402


def test_cost_aware_gate():
    assert G.cost_aware_gate(15.0, 9.0, marge_bps=1.0)["trade"] is True     # 15 > 9+1
    assert G.cost_aware_gate(9.5, 9.0, marge_bps=1.0)["trade"] is False     # 9.5 <= 10
    assert G.cost_aware_gate(None, 9.0)["trade"] is False                    # UNMEASURABLE -> no trade


def test_early_stop():
    assert G.early_stop(-5.0, 20) == "KILL"
    assert G.early_stop(3.0, 20) == "CONTINUE"
    assert G.early_stop(-5.0, 3) == "MORE_DATA"             # N insuffisant -> pas de KILL hatif
    assert G.early_stop(None, 50) == "MORE_DATA"


def test_multiple_testing_seuil_monte_avec_N():
    assert G.attendu_max_bruit_bps(1000, 2.0) > G.attendu_max_bruit_bps(10, 2.0)
    assert G.passe_multiple_testing(20.0, 2.0, 10)["passe"] is True
    assert G.passe_multiple_testing(1.0, 2.0, 1000)["passe"] is False


def test_verdict_final():
    assert G.verdict_final(lcb_net_bps=5.0, n_independent=30, sigma_bps=1.0, n_trials=10, cost_incomplet=True) == "MORE_DATA"
    assert G.verdict_final(lcb_net_bps=20.0, n_independent=30, sigma_bps=1.0, n_trials=10, cost_incomplet=False) == "CANDIDAT"
    assert G.verdict_final(lcb_net_bps=-5.0, n_independent=30, sigma_bps=1.0, n_trials=10, cost_incomplet=False) == "KILL"
