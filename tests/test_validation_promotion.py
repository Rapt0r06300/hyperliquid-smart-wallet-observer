from hl_observer.research.validation_promotion import (
    reconstruire_chemins_cpcv, spa_test, stepm_romano_wolf, leave_one_out_cv,
    borne_basse_nette, protocole_sans_edge, verdict_promotion,
    PROMOTION_POSITIVE, NO_PROMOTION)


def test_cpcv_reconstruit_les_chemins():
    r = reconstruire_chemins_cpcv(4, 2)
    assert r["n_chemins"] == 6
    assert all(len(c["test"]) == 2 and len(c["train"]) == 2 for c in r["chemins"])


def test_spa_detecte_surperformance_reelle():
    ref = [0.0] * 60
    r = spa_test(ref, {"bon": [0.5] * 60, "nul": [0.0] * 60}, n_boot=300)
    assert r["significatif"] is True and r["meilleur"] == "bon"


def test_spa_rejette_si_pas_mieux():
    ref = [0.0] * 60
    r = spa_test(ref, {"a": [0.0] * 60}, n_boot=300)
    assert r["significatif"] is False


def test_stepm_controle_fwer():
    ref = [0.0] * 60
    r = stepm_romano_wolf(ref, {"A": [0.5] * 60, "B": [0.0] * 60}, n_boot=300)
    assert "A" in r["significatifs"] and "B" not in r["significatifs"]


def test_leave_one_out_generalise():
    # evaluer rend la valeur du groupe teste (proxy) : tous positifs -> generalise
    ev = lambda train, test: test
    assert leave_one_out_cv({"s1": 1.0, "s2": 1.0, "s3": 1.0}, ev)["generalise"] is True
    assert leave_one_out_cv({"s1": 1.0, "s2": -1.0}, ev)["generalise"] is False


def test_borne_basse_nette():
    assert borne_basse_nette([1.0] * 100)["borne_basse"] > 0
    assert borne_basse_nette([-5.0, 5.0] * 50)["borne_basse"] < 0


def test_protocole_sans_edge_bloque():
    assert protocole_sans_edge(0.3)["promotion_autorisee"] is True
    assert protocole_sans_edge(None)["promotion_autorisee"] is False
    assert protocole_sans_edge(-0.1)["promotion_autorisee"] is False


def test_verdict_promotion_deny_by_default():
    ok = verdict_promotion(borne_basse=1.5, edge_positif=True, drift_stable=True)
    assert ok["verdict"] == PROMOTION_POSITIVE and ok["raisons"] == []
    ko = verdict_promotion(borne_basse=-0.1, edge_positif=True, drift_stable=False)
    assert ko["verdict"] == NO_PROMOTION and "BORNE_BASSE_NETTE_NON_POSITIVE" in ko["raisons"] and "DRIFT_INSTABLE" in ko["raisons"]
