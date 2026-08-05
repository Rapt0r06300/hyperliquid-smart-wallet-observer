from hl_observer.research.validation_stats import (
    stationary_bootstrap, model_confidence_set, alpha_spending, intervalle_conforme)


def test_stationary_bootstrap_taille_et_determinisme():
    x = list(range(20))
    a = stationary_bootstrap(x, p=0.2, n=50, seed=1)
    assert a == stationary_bootstrap(x, p=0.2, n=50, seed=1)
    assert len(a) == 50 and all(len(s) == 20 for s in a)
    assert all(v in x for s in a for v in s)


def test_mcs_garde_les_equivalents_elimine_les_pires():
    pertes = {"bon": [1.0] * 10, "bon2": [1.01] * 10, "nul": [50.0] * 10}
    r = model_confidence_set(pertes, alpha=0.1)
    assert "nul" in r["elimines"] and "bon" in r["mcs"] and r["meilleur"] == "bon"


def test_alpha_spending_somme_a_alpha():
    for methode in ("bonferroni", "pocock", "obrien"):
        seuils = alpha_spending(4, alpha=0.05, methode=methode)
        assert len(seuils) == 4 and abs(sum(seuils) - 0.05) < 1e-9


def test_conforme_couvre_la_cible():
    residus = [0.1, -0.2, 0.3, -0.4, 0.5, -0.05, 0.15]
    r = intervalle_conforme(residus, alpha=0.1)
    couverts = sum(1 for e in residus if abs(e) <= r["demi_largeur"])
    assert couverts / len(residus) >= 0.9 - 1e-9
