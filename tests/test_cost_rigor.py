from hl_observer.research.cost_rigor import stress_couts, cout_point_in_time


def test_stress_couts_pire_cas():
    r = stress_couts([10.0] * 10, [1.0] * 10, multiplicateurs=(1.0, 2.0, 3.0))
    assert r["robuste_aux_couts"] is True and r["pire_multiplicateur"] == 3.0


def test_stress_couts_edge_fragile_detecte():
    r = stress_couts([10.0] * 10, [5.0] * 10, multiplicateurs=(1.0, 3.0))
    assert r["robuste_aux_couts"] is False and r["net_pire_cas"] < 0


def test_cout_point_in_time_pas_de_fuite():
    hist = [(0.0, 1.0), (10.0, 2.0), (20.0, 3.0)]
    assert cout_point_in_time(hist, 15.0)["cout"] == 2.0        # pas le cout futur 3.0
    assert cout_point_in_time(hist, 15.0)["asof"] == 10.0
    assert cout_point_in_time(hist, 5.0)["cout"] == 1.0
    assert cout_point_in_time(hist, -1.0)["cout"] is None        # aucun cout connu avant le trade
