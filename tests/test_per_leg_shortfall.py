"""[ARB #49] per-leg shortfall : écart prix réel vs attendu, calculé séparément pour A et B."""

import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE / "src"))

from hl_observer.arbitrage import per_leg_shortfall as PLS   # noqa: E402


def test_shortfall_oriente_cout():
    # achat payé plus cher que prévu -> shortfall positif (coût)
    assert PLS.shortfall_bps(100.1, 100.0, "ACHAT") == 10.0
    # vente encaissée moins cher que prévu -> shortfall positif aussi
    assert PLS.shortfall_bps(99.9, 100.0, "VENTE") == 10.0


def test_par_jambe_separe():
    r = PLS.shortfall_episode(
        {"prix_reel": 100.1, "prix_attendu": 100.0, "sens": "ACHAT"},
        {"prix_reel": 199.8, "prix_attendu": 200.0, "sens": "VENTE"})
    assert r["shortfall_a_bps"] == 10.0 and r["shortfall_b_bps"] == 10.0
    assert r["shortfall_total_bps"] == 20.0


def test_prix_manquant_non_mesurable():
    assert PLS.shortfall_bps(None, 100.0, "ACHAT") == "UNMEASURABLE"
    r = PLS.shortfall_episode({"prix_reel": None, "prix_attendu": 100.0, "sens": "ACHAT"},
                              {"prix_reel": 200.0, "prix_attendu": 200.0, "sens": "VENTE"})
    assert r["shortfall_total_bps"] == "UNMEASURABLE"
