from hl_observer.research.data_mesh import (
    DataMesh, ablation_sources, verifier_frequence, REQUIRED, OPTIONAL)


def test_registre_sources_et_requises():
    m = DataMesh()
    m.enregistrer("hyperliquid", statut=REQUIRED, licence="public", cout_api_usd=0.0, qualite=0.9)
    m.enregistrer("nansen", statut=OPTIONAL, licence="payante", cout_api_usd=100.0, qualite=0.7)
    assert m.sources_par_statut(REQUIRED) == ["hyperliquid"]
    assert m.requises_presentes(["hyperliquid"])["ok"] is True
    assert m.requises_presentes([])["manquantes"] == ["hyperliquid"]
    assert m.cout_total_api() == 100.0


def test_lineage():
    m = DataMesh()
    m.declarer_lineage("features_gold", ["hyperliquid", "binance"])
    assert m.lineage("features_gold") == ["hyperliquid", "binance"]


def test_ablation_sources_valeur_marginale():
    def ev(retires):
        return 1.0 - (0.4 if "A" in retires else 0.0) - (0.05 if "B" in retires else 0.0)
    r = ablation_sources(["A", "B"], ev)
    assert r[0]["source"] == "A" and abs(r[0]["valeur_marginale"] - 0.4) < 1e-9


def test_frequence_macro_detecte_sur_echantillonnage():
    lent = [0.0, 3600.0, 7200.0]
    assert verifier_frequence(lent, periode_attendue_s=3600.0)["ok"] is True
    rapide = [0.0, 60.0, 120.0]
    assert verifier_frequence(rapide, periode_attendue_s=3600.0)["ok"] is False
