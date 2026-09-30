"""[pépite 238] one-level adverse stress : simuler la consommation d'un niveau supplémentaire du carnet."""

import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE / "src"))

from hl_observer.arbitrage.adverse_level_stress import stresser   # noqa: E402


def test_stress_un_niveau():
    niveaux = [(100.0, 1.0), (100.5, 1.0), (101.0, 1.0)]
    r = stresser(niveaux, 1.0, niveaux_adverses=1, edge_base_bps=100.0)
    # base = 100 (niveau 0), stresse = 100.5 (saut 1) -> ~50 bps de degradation
    assert r["vwap_base"] == 100.0 and r["vwap_stresse"] == 100.5
    assert r["degradation_bps"] == 50.0 and r["edge_survit"] is True


def test_edge_ne_survit_pas():
    niveaux = [(100.0, 1.0), (110.0, 1.0)]
    r = stresser(niveaux, 1.0, niveaux_adverses=1, edge_base_bps=100.0)
    assert r["edge_survit"] is False                     # 1000 bps de degradation > 100


def test_carnet_insuffisant():
    assert stresser([(100.0, 1.0)], 1.0, niveaux_adverses=1)["vwap_stresse"] == "UNMEASURABLE"
