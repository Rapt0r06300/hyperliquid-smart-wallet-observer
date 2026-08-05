from hl_observer.research.qa_rigor import (
    detecter_flaky, auditer_timeouts, detecter_dependance_ordre,
    cas_pairwise, couverture_t_way, rapport_couverture_combinatoire,
    verifier_regression_memoire, soak_test)


def test_flaky_repere_l_instable():
    r = detecter_flaky({"a": [True, True, True], "b": [True, False, True]})
    assert r["flaky"] == ["b"] and r["stable"] == ["a"]


def test_audit_timeouts_signale_les_manquants():
    r = auditer_timeouts([{"nom": "api1", "timeout_s": 5}, {"nom": "api2"}])
    assert r["complet"] is False and r["sans_timeout"] == ["api2"]


def test_dependance_ordre_detectee():
    r = detecter_dependance_ordre([{"t1": True, "t2": True}, {"t1": True, "t2": False}])
    assert r["independant"] is False and r["coupables"] == ["t2"]


def test_pairwise_couvre_toutes_les_paires_et_reduit():
    params = {"a": [1, 2], "b": ["x", "y"], "c": [True, False], "d": [0, 1]}
    cas = cas_pairwise(params)
    assert abs(couverture_t_way(cas, params, t=2) - 1.0) < 1e-9
    assert len(cas) < 16


def test_rapport_couverture_publie():
    params = {"a": [1, 2], "b": ["x", "y"]}
    cas = cas_pairwise(params)
    r = rapport_couverture_combinatoire(cas, params, t=2)
    assert r["couverture_t_way"] == 1.0 and r["factoriel_complet"] == 4


def test_regression_memoire_detectee():
    assert verifier_regression_memoire(100.0, 120.0, tolerance=0.10)["regression"] is True
    assert verifier_regression_memoire(100.0, 105.0, tolerance=0.10)["regression"] is False


def test_soak_detecte_la_fuite():
    assert soak_test([10, 11, 12, 13, 14, 15])["fuite"] is True
    assert soak_test([10, 10, 9, 10, 11, 9])["fuite"] is False
