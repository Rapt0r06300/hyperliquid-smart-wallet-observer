"""[ARB #37] connector reliability premium : une venue instable exige un edge supérieur."""

import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE / "src"))

from hl_observer.arbitrage import connector_reliability_premium as CRP   # noqa: E402


def test_premium_croit_quand_fiabilite_baisse():
    assert CRP.premium_bps(1.0, premium_max_bps=50.0) == 0.0
    assert CRP.premium_bps(0.8, premium_max_bps=50.0) == 10.0
    assert CRP.premium_bps(None, premium_max_bps=50.0) == 50.0        # inconnu = pire cas


def test_venue_admissible_selon_seuil():
    ok = CRP.venue_admissible(45.0, edge_base_bps=30.0, fiabilite=0.8)   # seuil = 30+10 = 40
    assert ok["admissible"] is True and ok["seuil_bps"] == 40.0
    ko = CRP.venue_admissible(35.0, edge_base_bps=30.0, fiabilite=0.8)
    assert ko["admissible"] is False


def test_edge_non_mesurable_refuse():
    assert CRP.venue_admissible(None, edge_base_bps=30.0, fiabilite=0.9)["admissible"] is False
