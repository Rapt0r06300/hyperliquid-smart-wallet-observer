from hl_observer.research.research_governance import (
    dedup_clones_economiques, comparer_orchestrateurs,
    garde_optimiseurs_max, resultat_identique_apres_unification)


def test_dedup_clones_economiques():
    r = dedup_clones_economiques([
        {"id": "a", "signature_economique": "S1"},
        {"id": "b", "signature_economique": "S1"},
        {"id": "c", "signature_economique": "S2"}])
    assert r["n_uniques"] == 2 and r["n_doublons"] == 1


def test_comparer_orchestrateurs():
    assert comparer_orchestrateurs({"A": {"pnl": 10}, "B": {"pnl": 10}})["identiques"] is True
    r = comparer_orchestrateurs({"A": {"pnl": 10}, "B": {"pnl": 20}})
    assert r["identiques"] is False and len(r["divergents"]) >= 1


def test_garde_optimiseurs_max_signale_absent():
    r = garde_optimiseurs_max(["optuna", "sobol", "genetic"], ["optuna", "genetic"])
    assert r["complet"] is False and r["manquants"] == ["sobol"]


def test_resultat_identique_apres_unification():
    assert resultat_identique_apres_unification(10.0, 10.0)["identique"] is True
    assert resultat_identique_apres_unification(10.0, 10.5)["identique"] is False
    assert resultat_identique_apres_unification({"a": 1}, {"a": 1})["identique"] is True
