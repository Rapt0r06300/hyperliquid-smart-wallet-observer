from hl_observer.research.scenario_rigor import (
    couverture_scenarios, ablation_sweep, contrefactuels_systematiques,
    clusterer_erreurs, evaluer_transfert, simuler_marche_agent_based, rapport_maximum_pistes)


def test_couverture_scenarios_mesure_les_manquants():
    r = couverture_scenarios(["calme", "volatil", "gap"], ["calme", "gap"])
    assert r["manquants"] == ["volatil"] and abs(r["taux"] - 2 / 3) < 1e-9


def test_ablation_classe_par_importance():
    def ev(retires):
        return 1.0 - (0.5 if "A" in retires else 0.0) - (0.1 if "B" in retires else 0.0)
    r = ablation_sweep(["A", "B"], ev)
    assert r[0]["composant"] == "A" and abs(r[0]["delta"] - 0.5) < 1e-9


def test_contrefactuels_effet_marginal():
    r = contrefactuels_systematiques(["x", "y"], lambda d: 1.0 if d["x"] else 0.0)
    d = {e["facteur"]: e["effet_marginal_moyen"] for e in r}
    assert abs(d["x"] - 1.0) < 1e-9 and abs(d["y"]) < 1e-9


def test_clusterer_erreurs_par_frequence():
    errs = [{"signature": "A"}, {"signature": "B"}, {"signature": "A"}, {"signature": "A"}]
    r = clusterer_erreurs(errs)
    assert r[0]["signature"] == "A" and r[0]["n"] == 3


def test_transfert_detecte_echec():
    r = evaluer_transfert({"BTC": 0.5, "ETH": -0.2, "SOL": 0.3})
    assert r["transfere_partout"] is False and r["echecs"] == ["ETH"]


def test_marche_synthetique_etiquete_et_deterministe():
    a = simuler_marche_agent_based(50, seed=3)
    b = simuler_marche_agent_based(50, seed=3)
    assert a["data_origin"] == "SYNTHETIQUE" and a["real_execution"] is False
    assert a["prix"] == b["prix"] and len(a["prix"]) == 51


def test_rapport_maximum_pistes_trie_tout():
    r = rapport_maximum_pistes([{"id": "a", "score": 1}, {"id": "b", "score": 9}, {"id": "c", "score": 5}])
    assert r["n_pistes"] == 3 and r["meilleure"]["id"] == "b"
    assert [p["id"] for p in r["pistes"]] == ["b", "c", "a"]
