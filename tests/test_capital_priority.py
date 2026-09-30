from hl_observer.execution_core.capital_priority import allouer_avec_priorite_strict


def test_strict_servi_avant_exploratoire():
    r = allouer_avec_priorite_strict({"strict": 80.0, "alpha": 40.0})
    assert r["allocation"]["strict"] == 80.0
    assert r["allocation"]["alpha"] == 20.0
    assert r["strict_servi_avant_exploratoire"] is True


def test_strict_ne_peut_pas_etre_affame():
    r = allouer_avec_priorite_strict({"strict": 120.0, "alpha": 50.0})
    assert r["allocation"]["strict"] == 100.0
    assert r["allocation"]["alpha"] == 0.0
    assert r["reste_exploratoire"] == 0.0


def test_prorata_du_reste_entre_exploratoires():
    r = allouer_avec_priorite_strict({"strict": 60.0, "alpha": 30.0, "probe": 10.0})
    assert r["allocation"]["strict"] == 60.0
    assert r["allocation"]["alpha"] == 30.0 and r["allocation"]["probe"] == 10.0
