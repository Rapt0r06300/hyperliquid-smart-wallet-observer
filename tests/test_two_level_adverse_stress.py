"""[pépite 239] two-level adverse stress : même simulation avec deux niveaux consommés (marchés plus fins)."""

import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE / "src"))

from hl_observer.arbitrage.adverse_level_stress import stresser   # noqa: E402


def test_stress_deux_niveaux():
    niveaux = [(100.0, 1.0), (100.5, 1.0), (101.0, 1.0)]
    r = stresser(niveaux, 1.0, niveaux_adverses=2, edge_base_bps=200.0)
    # saut de 2 niveaux -> vwap = 101.0
    assert r["vwap_stresse"] == 101.0 and r["degradation_bps"] == 100.0


def test_deux_niveaux_plus_severe_qu_un():
    niveaux = [(100.0, 1.0), (100.5, 1.0), (101.0, 1.0)]
    un = stresser(niveaux, 1.0, niveaux_adverses=1)
    deux = stresser(niveaux, 1.0, niveaux_adverses=2)
    assert deux["degradation_bps"] > un["degradation_bps"]


def test_carnet_insuffisant_deux_niveaux():
    assert stresser([(100.0, 1.0), (100.5, 1.0)], 1.0, niveaux_adverses=2)["vwap_stresse"] == "UNMEASURABLE"
