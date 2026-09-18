from hl_observer.execution_core.enveloppe_capital_unique import (
    ENVELOPPE_MASTER_USD, verifier_enveloppe)


def test_somme_dans_l_enveloppe_respecte():
    r = verifier_enveloppe({"strict": 60.0, "alpha": 30.0, "probe": 10.0})
    assert r["respecte"] is True and r["total_engage"] == 100.0 and r["depassement"] == 0.0


def test_budget_exploratoire_additif_depasse():
    r = verifier_enveloppe({"experimental": 100.0, "exploratoire": 30.0})
    assert r["respecte"] is False and r["depassement"] == 30.0 and "DEPASSEE" in r["raison"]


def test_master_est_100():
    assert ENVELOPPE_MASTER_USD == 100.0
    assert verifier_enveloppe({"x": 100.0})["respecte"] is True
    assert verifier_enveloppe({"x": 100.01})["respecte"] is False
