from hl_observer.ops.recommendation_tracking import suivre_recommandation


def test_reco_qui_aide():
    r = suivre_recommandation(avant=-5.0, apres=2.0, sens="hausse", delta_attendu=5.0)
    assert r["delta"] == 7.0 and r["a_aide"] is True and r["objectif_atteint"] is True


def test_reco_qui_n_aide_pas():
    r = suivre_recommandation(avant=10.0, apres=8.0, sens="hausse")
    assert r["delta"] == -2.0 and r["a_aide"] is False


def test_sens_baisse():
    r = suivre_recommandation(avant=10.0, apres=3.0, sens="baisse", delta_attendu=5.0)
    assert r["a_aide"] is True and r["objectif_atteint"] is True
