from hl_observer.execution_core.capital_priority import allouer_avec_priorite_strict


def test_strict_servi_avant_exploratoire():
    r = allouer_avec_priorite_strict({"strict": 800.0, "alpha": 400.0})
    assert r["allocation"]["strict"] == 800.0
    assert r["allocation"]["alpha"] == 200.0
    assert r["strict_servi_avant_exploratoire"] is True


def test_strict_ne_peut_pas_etre_affame():
    r = allouer_avec_priorite_strict({"strict": 1200.0, "alpha": 500.0})
    assert r["allocation"]["strict"] == 1000.0
    assert r["allocation"]["alpha"] == 0.0
    assert r["reste_exploratoire"] == 0.0


def test_prorata_du_reste_entre_exploratoires():
    r = allouer_avec_priorite_strict({"strict": 600.0, "alpha": 300.0, "probe": 100.0})
    assert r["allocation"]["strict"] == 600.0
    assert r["allocation"]["alpha"] == 300.0 and r["allocation"]["probe"] == 100.0
