"""[pépite 240] partial-asymmetry precheck : tester 25/50/75/100% fill A vs couverture réalisable de B."""

import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE / "src"))

from hl_observer.arbitrage.partial_asymmetry_precheck import precheck   # noqa: E402


def test_tous_scenarios_ok():
    r = precheck(taille_a=1.0, couverture_b=lambda q: 10.0, edge_plein_bps=10.0, perte_max_bps=30.0)
    assert r["ok"] is True and len(r["scenarios"]) == 4


def test_scenario_partiel_perdant():
    # un fill partiel donne -50 bps -> refuse
    def cov(q):
        return -50.0 if q < 1.0 else 10.0
    r = precheck(taille_a=1.0, couverture_b=cov, edge_plein_bps=10.0, perte_max_bps=30.0)
    assert r["ok"] is False and r["raison"] == "SCENARIO_PARTIEL_TROP_PERDANT"


def test_entree_invalide():
    assert precheck(taille_a=0.0, couverture_b=lambda q: 1.0, edge_plein_bps=10.0)["ok"] is False
