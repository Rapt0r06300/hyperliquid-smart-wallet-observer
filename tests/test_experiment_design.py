from hl_observer.research.experiment_design import (
    plan_factoriel, suite_basse_discrepance, successive_halving, classer_par_information_gain)


def test_plan_factoriel_produit_cartesien():
    p = plan_factoriel({"a": [1, 2], "b": ["x", "y", "z"]})
    assert len(p) == 6
    assert {"a": 1, "b": "x"} in p and {"a": 2, "b": "z"} in p


def test_halton_dans_unit_et_deterministe():
    s1 = suite_basse_discrepance(2, 5)
    assert s1 == suite_basse_discrepance(2, 5)
    assert all(0.0 <= x < 1.0 and 0.0 <= y < 1.0 for x, y in s1)
    assert abs(s1[0][0] - 0.5) < 1e-9


def test_successive_halving_garde_le_meilleur():
    assert successive_halving([1, 5, 3, 9, 2, 8], lambda c, b: c, facteur=2) == [9]


def test_information_gain_ordonne_par_incertitude():
    r = classer_par_information_gain([{"id": "a", "incertitude": 0.1},
                                      {"id": "b", "incertitude": 0.9},
                                      {"id": "c", "incertitude": 0.5}])
    assert [d["id"] for d in r] == ["b", "c", "a"] and r[0]["rang"] == 1
