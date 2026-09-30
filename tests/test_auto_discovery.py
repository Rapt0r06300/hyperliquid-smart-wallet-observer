from hl_observer.research.auto_discovery import (
    generer_features, penalite_complexite, regression_symbolique,
    recherche_genetique, ArchiveMapElites, quarantaine_generateur, QUARANTAINE)


def test_generer_features_nomme_et_trace():
    f = generer_features(["a", "b"], lags=[1, 2])
    assert "a^2" in f and "a[t-2]" in f and "a/b" in f


def test_penalite_complexite_reduit_le_score():
    assert penalite_complexite(1.0, 5, lambda_=0.1) == 0.5


def test_regression_symbolique_retrouve_lineaire():
    xs = [1, 2, 3, 4, 5]
    ys = [2 * x for x in xs]
    r = regression_symbolique(xs, ys)
    assert r["forme"] == "x" and r["r2"] > 0.999 and abs(r["a"] - 2.0) < 1e-6


def test_recherche_genetique_compte_dans_le_registre():
    reg = []
    r = recherche_genetique([0.0, 0.1, -0.2], lambda v: -(v - 3.0) ** 2, generations=12, registre=reg)
    assert abs(r["meilleur"] - 3.0) < 1.0 and len(reg) > 0


def test_map_elites_garde_le_meilleur_par_niche():
    a = ArchiveMapElites()
    assert a.proposer("x", "n1", 0.5) is True
    assert a.proposer("y", "n1", 0.3) is False
    assert a.proposer("z", "n2", 0.1) is True
    assert a.couverture() == 2


def test_quarantaine_bloque_la_promotion():
    q = quarantaine_generateur([{"id": "h1"}, {"id": "h2"}])
    assert all(h["statut"] == QUARANTAINE and h["promotion_autorisee"] is False for h in q)
