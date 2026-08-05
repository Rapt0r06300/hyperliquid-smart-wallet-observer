from hl_observer.simulation.exploratory_vs_validated_pnl import (
    TIER_EXPLORATOIRE, TIER_VALIDE, pnl_valide_seulement, tier_pnl)


def test_tier():
    assert tier_pnl("strict") == TIER_VALIDE
    assert tier_pnl("ALPHA") == TIER_EXPLORATOIRE and tier_pnl("raw_probe") == TIER_EXPLORATOIRE


def test_pas_de_melange():
    r = pnl_valide_seulement({"strict": 12.0, "alpha": 5.0, "raw_probe": -2.0})
    assert r["pnl_valide"] == 12.0                 # seul le strict
    assert r["pnl_exploratoire_separe"] == 3.0     # alpha + probe, SEPARE
    assert r["melange_interdit"] is True
