from hl_observer.ops.improvement_verdict import ANNULER, CONSERVER, verdict_amelioration


def test_conserver_si_gain():
    r = verdict_amelioration(avant=-5.0, apres=1.0, seuil=0.0)
    assert r["verdict"] == CONSERVER and r["gain_net"] == 6.0 and r["rollback"] is False


def test_annuler_si_pas_de_gain():
    r = verdict_amelioration(avant=5.0, apres=4.0, seuil=0.0)
    assert r["verdict"] == ANNULER and r["rollback"] is True


def test_seuil_respecte():
    assert verdict_amelioration(avant=0.0, apres=0.5, seuil=1.0)["verdict"] == ANNULER
    assert verdict_amelioration(avant=0.0, apres=1.5, seuil=1.0)["verdict"] == CONSERVER
