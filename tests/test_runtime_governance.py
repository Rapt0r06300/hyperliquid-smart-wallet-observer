from hl_observer.ops.runtime_governance import (
    detecter_derive_execution, RegistreOrchestrateurs, CANONIQUE)


def test_derive_execution_detectee():
    base = {"cout_bps": 2.0, "fill_rate": 0.9, "latence_ms": 50.0}
    cur = {"cout_bps": 2.1, "fill_rate": 0.6, "latence_ms": 52.0}
    r = detecter_derive_execution(base, cur, tolerance=0.20)
    assert r["stable"] is False and "fill_rate" in r["derives"] and "cout_bps" not in r["derives"]


def test_orchestrateurs_unifies():
    reg = RegistreOrchestrateurs()
    reg.enregistrer(CANONIQUE, "canonique")
    reg.enregistrer("global_observer_pipeline", "secondaire")
    r = reg.verifier_unicite()
    assert r["unifie"] is True and r["n_orchestrateurs"] == 2


def test_deux_canoniques_casse_l_unification():
    reg = RegistreOrchestrateurs()
    reg.enregistrer(CANONIQUE, "canonique")
    reg.enregistrer("autre_moteur", "canonique")
    assert reg.verifier_unicite()["unifie"] is False
