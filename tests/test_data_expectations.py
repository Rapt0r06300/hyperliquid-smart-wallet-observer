from hl_observer.data_contract.expectations import ContratDonnees


def test_contrat_valide_les_bonnes_lignes():
    c = ContratDonnees().non_null("px").dans_plage("px", 0, 1e9).dans_ensemble("side", ["BUY", "SELL"])
    r = c.valider([{"px": 100.0, "side": "BUY"}, {"px": 50.0, "side": "SELL"}])
    assert r["valide"] is True and r["violations"] == []


def test_contrat_attrape_les_violations():
    c = ContratDonnees().non_null("px").dans_plage("px", 0, 100).dans_ensemble("side", ["BUY", "SELL"])
    r = c.valider([{"px": None, "side": "BUY"}, {"px": 999, "side": "HOLD"}])
    assert r["valide"] is False
    regles = {(v["ligne"], v["regle"]) for v in r["violations"]}
    assert (0, "non_null") in regles and (1, "plage") in regles and (1, "ensemble") in regles
