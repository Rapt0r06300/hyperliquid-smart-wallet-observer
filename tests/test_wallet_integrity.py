from hl_observer.research.wallet_integrity import (
    detecter_sybils, transferts_hors_pnl, correction_survivorship,
    inclure_wallets_liquides, consensus_pondere_independance, seuil_confiance_merge)


def test_detecter_sybils():
    r = detecter_sybils({("w1", "w2"): 0.98, ("w1", "w3"): 0.4})
    assert r["sybils_suspects"] == [("w1", "w2")]


def test_transferts_hors_pnl():
    mv = [{"type": "trade", "montant": 10.0}, {"type": "deposit", "montant": 1000.0}, {"type": "trade", "montant": -3.0}]
    r = transferts_hors_pnl(mv)
    assert r["pnl"] == 7.0 and r["transferts_exclus"] == 1000.0 and r["n_transferts"] == 1


def test_correction_survivorship():
    r = correction_survivorship(["a", "b", "c", "d"], ["a", "b"])
    assert r["disparus"] == ["c", "d"] and r["biais_present"] is True and r["taux_disparition"] == 0.5


def test_inclure_wallets_liquides():
    assert inclure_wallets_liquides([{"id": "a", "liquide": False}])["cohorte_suspecte"] is True
    assert inclure_wallets_liquides([{"id": "a", "liquide": True}])["cohorte_suspecte"] is False


def test_consensus_pondere_independance():
    # w1,w2,w3 = meme acteur (groupe G) votent 1 ; w4 (groupe H) vote 0 -> 2 voix, consensus 0.5
    votes = {"w1": 1.0, "w2": 1.0, "w3": 1.0, "w4": 0.0}
    groupes = {"w1": "G", "w2": "G", "w3": "G", "w4": "H"}
    r = consensus_pondere_independance(votes, groupes)
    assert r["n_voix_independantes"] == 2 and abs(r["consensus"] - 0.5) < 1e-9


def test_seuil_confiance_merge():
    liens = [{"a": "x", "b": "y", "confiance": 0.9}, {"a": "x", "b": "z", "confiance": 0.5}]
    r = seuil_confiance_merge(liens)
    assert r["merges_retenus"] == [("x", "y")] and r["merges_rejetes"] == [("x", "z")]
