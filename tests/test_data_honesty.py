from hl_observer.research.data_honesty import (
    interdire_success_si_zero_donnee, distinguer_zero, detecter_carry_forward_silencieux,
    rejeter_donnees_revisees_non_pit, quarantaine_champs_inconnus)


def test_pas_de_success_sur_zero_donnee():
    assert interdire_success_si_zero_donnee("SUCCESS", 0)["honnete"] is False
    assert interdire_success_si_zero_donnee("SUCCESS", 0)["statut_corrige"] == "NO_DATA"
    assert interdire_success_si_zero_donnee("SUCCESS", 5)["honnete"] is True


def test_distinguer_zero_mesure_vs_invente():
    assert distinguer_zero(0, mesuree=True) == {"valeur": 0, "etat": "MESURE"}
    assert distinguer_zero(0, mesuree=False)["valeur"] is None


def test_carry_forward_silencieux():
    serie = [{"valeur": 3773, "source_ts": 100}, {"valeur": 3773, "source_ts": 100}]
    assert detecter_carry_forward_silencieux(serie)["carry_forward"] is True
    frais = [{"valeur": 3773, "source_ts": 100}, {"valeur": 3800, "source_ts": 200}]
    assert detecter_carry_forward_silencieux(frais)["carry_forward"] is False


def test_rejeter_revisees_non_pit():
    recs = [{"revised": True, "asof": None}, {"revised": True, "asof": 100.0}, {"revised": False}]
    r = rejeter_donnees_revisees_non_pit(recs)
    assert r["ok"] is False and r["rejetes"] == [0]


def test_quarantaine_champs_inconnus():
    r = quarantaine_champs_inconnus({"px": 1, "sz": 2, "mystere": 9}, ["px", "sz"])
    assert r["quarantaine"] == ["mystere"] and r["propre"] == {"px": 1, "sz": 2}
