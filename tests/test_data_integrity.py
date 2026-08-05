from hl_observer.research.data_integrity import (
    courbe_apprentissage_oos, detecter_modules_sans_appelant, scanner_except_larges,
    detecter_derive_tasklist, adaptateur_unique_live_replay, detecter_collecteurs_doublons,
    correspondance_registre_lanceur_superviseur, attribuer_ressources_par_source)


def test_courbe_apprentissage_oos():
    croissant = [{"taille": 100, "perf_oos": 0.1}, {"taille": 200, "perf_oos": 0.2}, {"taille": 400, "perf_oos": 0.3}]
    assert courbe_apprentissage_oos(croissant)["ameliore"] is True
    plat_negatif = [{"taille": 100, "perf_oos": 0.3}, {"taille": 400, "perf_oos": 0.1}]
    assert courbe_apprentissage_oos(plat_negatif)["ameliore"] is False


def test_detecter_modules_sans_appelant():
    imports = {"a": ["b"], "b": [], "orphelin": []}
    r = detecter_modules_sans_appelant(imports, points_entree=["a"])
    assert r["modules_morts"] == ["orphelin"]


def test_scanner_except_larges():
    code = ["    try:", "        x()", "    except Exception:", "        pass", "    except ValueError:"]
    r = scanner_except_larges(code)
    assert r["except_larges"] == [2] and r["n"] == 1


def test_detecter_derive_tasklist():
    r = detecter_derive_tasklist(["AUD-1", "AUD-2"], ["AUD-1", "AUD-3"])
    assert r["coherent"] is False and r["manquants_dans_fichier"] == ["AUD-2"] and r["en_trop_dans_fichier"] == ["AUD-3"]


def test_adaptateur_unique_live_replay():
    assert adaptateur_unique_live_replay({"hl": ["a", "a"], "binance": ["x", "y"]})["sources_a_double_adaptateur"] == ["binance"]


def test_detecter_collecteurs_doublons():
    cols = [{"nom": "c1", "venue": "hl", "stream": "book"}, {"nom": "c2", "venue": "hl", "stream": "book"}]
    assert detecter_collecteurs_doublons(cols)["doublons"] == ["c2"]


def test_correspondance_registre_lanceur_superviseur():
    r = correspondance_registre_lanceur_superviseur(["a", "b"], ["a"], ["a", "b"])
    assert r["coherent"] is False and r["non_lances"] == ["b"]


def test_attribuer_ressources_par_source():
    r = attribuer_ressources_par_source({"hl": {"cpu": 1.0, "ram_mo": 100}, "binance": {"cpu": 2.0}})
    assert r["total"]["cpu"] == 3.0 and r["total"]["ram_mo"] == 100.0
