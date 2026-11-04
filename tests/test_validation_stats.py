from hl_observer.research.validation_stats import (
    alpha_spending,
    calculer_pbo_toutes_les_tentatives,
    intervalle_conforme,
    model_confidence_set,
    pbo_all_attempts,
    stationary_bootstrap,
)
from hl_observer.research.deflated_sharpe import deflated_sharpe_all_attempts


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


def test_pbo_compte_toutes_les_tentatives_et_reste_deterministe():
    attempts = [
        {"attempt_id": "a", "performance_by_block": [2, 2, 2, 2]},
        {"attempt_id": "b", "performance_by_block": [1, 1, 1, 1]},
    ]
    result = pbo_all_attempts(attempts)
    assert result["status"] == "PROVEN"
    assert result["n_attempts_total"] == result["n_attempts_used"] == 2
    assert result["pbo"] == 0.0
    assert calculer_pbo_toutes_les_tentatives(attempts) == result


def test_pbo_refuse_une_tentative_incomplete_sans_zero_implicit():
    result = pbo_all_attempts([
        {"attempt_id": "ok", "performance_by_block": [1, 1, 1, 1]},
        {"attempt_id": "missing", "performance_by_block": None},
    ])
    assert result["status"] == "UNMEASURABLE"
    assert result["pbo"] is None
    assert result["n_attempts_total"] == 2
    assert result["n_attempts_used"] == 1
    assert result["invalid_attempt_ids"] == ["missing"]


def test_dsr_compare_tous_les_essais_et_compte_la_selection():
    attempts = [
        {"attempt_id": "a", "returns": [2, 1, 2, 1]},
        {"attempt_id": "b", "returns": [1, 1, 1, 2]},
        {"attempt_id": "c", "returns": [0, 1, 0, 1]},
    ]
    result = deflated_sharpe_all_attempts(attempts)
    assert result["status"] == "PROVEN"
    assert result["n_trials"] == result["n_attempts_total"] == 3
    assert result["candidate_id"] == "a"
    assert result["dsr"] is not None


def test_dsr_refuse_une_tentative_non_alignee_sans_la_supprimer():
    result = deflated_sharpe_all_attempts([
        {"attempt_id": "a", "returns": [2, 1, 2, 1]},
        {"attempt_id": "b", "returns": [1, 1, 1]},
    ])
    assert result["status"] == "UNMEASURABLE"
    assert result["dsr"] is None
    assert result["n_attempts_total"] == 2
    assert result["n_trials"] == 1
