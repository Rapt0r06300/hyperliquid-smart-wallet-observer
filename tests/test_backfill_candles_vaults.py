"""Backfill candles 5m sur les coins de vaults (rectif Flo 23/07) : lit les coins tradés + la fenêtre
depuis les fills, tire les candles par coin, détecte la troncature au cap 5000. Poster injecté (aucun
réseau)."""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]


def _mod(nom: str):
    spec = importlib.util.spec_from_file_location(nom, RACINE / "tools" / ("%s.py" % nom))
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


BC = _mod("backfill_candles_vaults")


def test_coins_et_fenetre(tmp_path):
    (tmp_path / "runtime" / "data").mkdir(parents=True)
    (tmp_path / "runtime" / "data" / "vault_fills.jsonl").write_text("\n".join([
        json.dumps({"coin": "BTC", "ts_ms": 1000}),
        json.dumps({"coin": "kPEPE", "ts_ms": 5000}),
        json.dumps({"coin": "xyz:XYZ100", "ts_ms": 6000}),
        json.dumps({"coin": "BTC", "ts_ms": 9000}),
    ]))
    coins, t0, t1 = BC.coins_et_fenetre(tmp_path)
    # identité NATIVE : l'ancienne mise en majuscules demandait KPEPE et XYZ:XYZ100, refusés par l'API
    assert set(coins) == {"BTC", "kPEPE", "xyz:XYZ100"} and t0 == 1000 and t1 == 9000


def test_backfill_un_coin_parse_et_detecte_troncature(tmp_path):
    from hl_observer.collection import collecte_fiable as CF
    # réponse candleSnapshot HL : liste de bougies {t,T,s,i,o,c,h,l,v}
    def poster(coin, interval, a, b):
        return [{"t": 1000 * i, "T": 1000 * i + 999, "s": coin, "i": interval,
                 "o": "100", "c": "101", "h": "102", "l": "99", "v": "10"} for i in range(3)]
    bougies, tronque = BC.backfill_un_coin("BTC", 0, 10000, limiteur=CF.Limiteur(0.0), poster=poster)
    assert len(bougies) == 3 and bougies[0]["coin"] == "BTC" and bougies[0]["c"] == 101.0 and tronque is False

    def poster_plein(coin, interval, a, b):                          # réponse au cap 5000 -> tronquée
        return [{"t": i, "T": i, "s": coin, "i": interval, "o": "1", "c": "1", "h": "1", "l": "1", "v": "1"}
                for i in range(BC.CAP_CANDLES)]
    _, tronque2 = BC.backfill_un_coin("BTC", 0, 10 ** 9, limiteur=CF.Limiteur(0.0), poster=poster_plein)
    assert tronque2 is True


# ------------------------------------------------------------------ passage incrémental, 1 h, cadence

HEURE = 3_600_000
NOW = 1_790_000_000_000 // HEURE * HEURE + 1_234_567        # 20 min 34 s après une heure pleine


def _serveur(appels):
    """Faux ``candleSnapshot`` : rend les bougies de l'intervalle demandé, dont celle encore en cours."""
    def poster(coin, intervalle, a, b):
        appels.append((coin, intervalle, a, b))
        pas = BC.INTERVALLES_MS[intervalle]
        premier = -(-a // pas) * pas
        return [{"t": t, "T": t + pas - 1, "s": coin, "i": intervalle,
                 "o": "100", "c": "101", "h": "102", "l": "99", "v": "5"} for t in range(premier, b + 1, pas)]
    return poster


def _lignes(chemin):
    return [json.loads(x) for x in chemin.read_text(encoding="utf-8").splitlines() if x.strip()]


def _racine(tmp_path, coins):
    (tmp_path / "config").mkdir(parents=True)
    (tmp_path / "config" / "copy_vault_coins.json").write_text(json.dumps({"coins": coins}), encoding="utf-8")
    return tmp_path


def test_passage_1h_rattrape_puis_n_ajoute_que_les_bougies_nouvelles_et_closes(tmp_path):
    root = _racine(tmp_path, ["BTC", "kPEPE", "xyz:XYZ100", "INCONNU"])
    appels, siestes = [], []
    univers = {"BTC", "kPEPE", "xyz:XYZ100"}
    bilan = BC.passe(root, intervalles=("1h",), now_ms=NOW, poster=_serveur(appels), dormir=siestes.append,
                     univers=univers)
    assert bilan["coins_inconnus_non_demandes"] == ["INCONNU"] and bilan["arret"] is None
    assert {a[0] for a in appels} == univers                       # noms natifs, jamais KPEPE ni XYZ:XYZ100
    lignes = _lignes(root / BC.SORTIES["1h"])
    par_coin = {c: [x for x in lignes if x["coin"] == c] for c in univers}
    # toute la profondeur offerte par l'API, moins la bougie encore en cours (la 5 000e)
    assert all(len(v) == BC.CAP_CANDLES - 1 for v in par_coin.values())
    assert all(x["interval"] == "1h" and x["source"] == "REST_BACKFILL_1H" and x["recv_ms"] == NOW for x in lignes)
    assert max(x["t_ms"] for x in lignes) + HEURE <= NOW            # la bougie en cours n'est PAS écrite
    assert len(siestes) == 3 and all(s >= 10.0 for s in siestes)    # cadence réellement respectée

    # une heure plus tard : une seule bougie nouvelle par coin, aucune ligne réécrite
    appels.clear()
    bilan = BC.passe(root, intervalles=("1h",), now_ms=NOW + HEURE, poster=_serveur(appels), dormir=siestes.append,
                     univers=univers)
    assert bilan["intervalles"]["1h"]["bougies"] == 3
    assert len(_lignes(root / BC.SORTIES["1h"])) == 3 * (BC.CAP_CANDLES - 1) + 3
    # rejoué au même instant : rien à demander, rien d'écrit (idempotent)
    appels.clear()
    bilan = BC.passe(root, intervalles=("1h",), now_ms=NOW + HEURE, poster=_serveur(appels), dormir=siestes.append,
                     univers=univers)
    assert appels == [] and bilan["intervalles"]["1h"]["a_jour"] == 3
    # état perdu : il est relu du ruban, sans doublon
    (root / BC.ETAT).unlink()
    BC.passe(root, intervalles=("1h",), now_ms=NOW + HEURE, poster=_serveur(appels), dormir=siestes.append,
             univers=univers)
    lignes = _lignes(root / BC.SORTIES["1h"])
    assert len({(x["coin"], x["t_ms"]) for x in lignes}) == len(lignes)


def test_refus_de_debit_on_n_insiste_pas_et_un_echec_ne_bloque_pas_les_autres(tmp_path):
    import urllib.error

    root = _racine(tmp_path, ["AAA", "BBB", "CCC"])

    def refuse(coin, intervalle, a, b):
        raise urllib.error.HTTPError("u", 429, "Too Many Requests", None, None)

    siestes = []
    bilan = BC.passe(root, intervalles=("1h",), now_ms=NOW, poster=refuse, dormir=siestes.append, univers=None)
    assert bilan["arret"] == "LIMITE_DEBIT" and siestes == [BC.ATTENTE_REFUS_S]      # une attente, un essai, arrêt
    assert not (root / BC.SORTIES["1h"]).exists()

    bon = _serveur([])

    def un_coin_casse(coin, intervalle, a, b):
        if coin == "BBB":
            raise urllib.error.HTTPError("u", 500, "Internal Server Error", None, None)
        return bon(coin, intervalle, a, b)

    bilan = BC.passe(root, intervalles=("1h",), now_ms=NOW, poster=un_coin_casse, dormir=lambda s: None, univers=None)
    assert bilan["intervalles"]["1h"]["echecs"] == ["BBB"] and bilan["arret"] is None
    assert {x["coin"] for x in _lignes(root / BC.SORTIES["1h"])} == {"AAA", "CCC"}


def test_budget_de_temps_le_passage_suivant_reprend_les_coins_en_retard(tmp_path):
    root = _racine(tmp_path, ["AAA", "BBB", "CCC"])
    tic = iter(range(0, 10_000, 40))
    bilan = BC.passe(root, intervalles=("1h",), now_ms=NOW, poster=_serveur([]), dormir=lambda s: None,
                     univers=None, budget_s=50.0, horloge=lambda: next(tic))
    assert bilan["arret"] == "BUDGET_DE_TEMPS"
    faits = {x["coin"] for x in _lignes(root / BC.SORTIES["1h"])}
    assert 0 < len(faits) < 3
    appels = []
    BC.passe(root, intervalles=("1h",), now_ms=NOW, poster=_serveur(appels), dormir=lambda s: None, univers=None)
    assert {a[0] for a in appels} == {"AAA", "BBB", "CCC"} - faits            # seuls les coins en retard


def test_les_bougies_1h_sont_certifiees_et_sans_intervalle_elles_sont_refusees():
    from hl_observer.datasets import coffre_certifie as C

    ligne = {"coin": "xyz:XYZ100", "t_ms": NOW // HEURE * HEURE - HEURE, "o": 100.0, "h": 102.0, "l": 99.0,
             "c": 101.0, "v": 5.0, "interval": "1h", "source": "REST_BACKFILL_1H"}
    assert C._FICHIERS_CONNUS["candles_1h.jsonl"] == (C.FAMILLE_CANDLE, "REST_BACKFILL_1H")
    sortie, statut, _ = C.certifier_candle(ligne, source="REST_BACKFILL_1H", now_ms=NOW)
    assert statut in {C.PASS, C.REPARE} and sortie["interval"] == "1h" and sortie["coin"] == "xyz:XYZ100"
    assert sortie["causal_forward_eligible"] is False                # récupérée après coup, jamais « observée »
    sans = {k: v for k, v in ligne.items() if k != "interval"}
    assert C.certifier_candle(sans, source="REST_BACKFILL_1H", now_ms=NOW)[0]["interval"] == "1h"
    assert C.certifier_candle(sans, source="REST_BACKFILL_5M", now_ms=NOW)[0]["interval"] == "5m"
    refus = C.certifier_candle(sans, source="SOURCE_SANS_INTERVALLE", now_ms=NOW)
    assert refus[0] is None and refus[2] == "intervalle_absent"
    # même ouverture, deux intervalles : deux identités distinctes au coffre
    cinq = {**ligne, "interval": "5m"}
    assert C.identite(ligne, C.FAMILLE_CANDLE) != C.identite(cinq, C.FAMILLE_CANDLE)



# ------------------------------------------------------------------ historique horaire du funding

def _serveur_funding(appels, *, debut=NOW - 1300 * HEURE):
    """Faux ``fundingHistory`` : un point par heure depuis ``debut``, 500 par réponse au plus."""
    def poster(coin, a, b):
        appels.append((coin, a, b))
        instants = [t for t in range(debut, b + 1, HEURE) if t >= a][:BC.PAGE_FUNDING]
        return [{"coin": coin, "fundingRate": "0.0000125", "premium": "0.0001", "time": t} for t in instants]
    return poster


def test_funding_pagine_jusqu_au_bout_puis_n_ajoute_que_les_heures_nouvelles(tmp_path):
    root = _racine(tmp_path, ["BTC", "xyz:XYZ100"])
    appels, siestes = [], []
    bilan = BC.passe_funding(root, now_ms=NOW, poster=_serveur_funding(appels), dormir=siestes.append, univers=None)
    lignes = _lignes(root / BC.SORTIE_FUNDING)
    par_coin = {c: [x["ts_ms"] for x in lignes if x["coin"] == c] for c in ("BTC", "xyz:XYZ100")}
    attendu = list(range(NOW - 1300 * HEURE, NOW + 1, HEURE))
    assert all(v == attendu for v in par_coin.values())                 # 1 301 heures, 3 pages, aucun trou ni doublon
    assert bilan["demandes"] == 6 and bilan["points"] == 2 * len(attendu) and bilan["arret"] is None
    assert all(x["funding"] == 0.0000125 and x["interval"] == "1h" and x["source"] == "REST_FUNDING_HISTORY"
               and x["recv_ms"] == NOW for x in lignes)
    assert len(siestes) == 6 and all(s >= 2.0 for s in siestes)          # cadence respectée à chaque page
    # deux heures plus tard : deux points par coin, rien de réécrit
    appels.clear()
    encore = BC.passe_funding(root, now_ms=NOW + 2 * HEURE, poster=_serveur_funding(appels), dormir=siestes.append,
                              univers=None)
    assert encore["points"] == 4 and len(_lignes(root / BC.SORTIE_FUNDING)) == 2 * len(attendu) + 4
    # l'état des bougies et celui du funding cohabitent dans le même fichier sans s'écraser
    BC.passe(root, intervalles=("1h",), now_ms=NOW + 2 * HEURE, poster=_serveur([]), dormir=lambda s: None, univers=None)
    etat = json.loads((root / BC.ETAT).read_text(encoding="utf-8"))["intervalles"]
    assert set(etat) == {"1h", BC.SERIE_FUNDING} and set(etat[BC.SERIE_FUNDING]) == {"BTC", "xyz:XYZ100"}


def test_funding_point_illisible_ecarte_et_certification_stricte():
    from hl_observer.datasets import coffre_certifie as C

    def poster(coin, a, b):
        return [{"coin": coin, "fundingRate": "0.00001", "premium": "0.0", "time": NOW - HEURE},
                {"coin": coin, "fundingRate": "abc", "time": NOW - 2 * HEURE},
                {"coin": coin, "fundingRate": "5.0", "time": NOW - 3 * HEURE},        # 500 % par heure : absurde
                {"coin": coin, "time": NOW - 4 * HEURE}, "pas un point"]

    lignes, pleine, erreur = BC.tirer_funding("BTC", 0, NOW, poster=poster)
    assert [x["ts_ms"] for x in lignes] == [NOW - HEURE] and pleine is False and erreur is None
    assert C._FICHIERS_CONNUS["funding_1h.jsonl"] == (C.FAMILLE_FUNDING_HISTORY, "REST_FUNDING_HISTORY")

    def juger(ligne):
        return C.certifier_record(ligne, famille=C.FAMILLE_FUNDING_HISTORY, source="REST_FUNDING_HISTORY", now_ms=NOW)

    sortie, statut, _ = juger(lignes[0])
    assert statut == C.PASS and sortie["funding"] == 0.00001 and sortie["causal_forward_eligible"] is False
    for motif, casse in {"coin_absent": {"coin": ""}, "timestamp_absent": {"ts_ms": None},
                         "timestamp_futur": {"ts_ms": NOW + 10 * HEURE}, "taux_invalide": {"funding": float("nan")},
                         }.items():
        assert juger({**lignes[0], **casse})[1:] == (C.QUARANTAINE, motif)
    assert juger({**lignes[0], "funding": 1.5})[2] == "taux_invalide"
    assert C.identite(lignes[0], C.FAMILLE_FUNDING_HISTORY) != C.identite({**lignes[0], "ts_ms": NOW}, C.FAMILLE_FUNDING_HISTORY)


def test_le_labo_lit_le_funding_historique_comme_le_funding_observe(tmp_path):
    import gzip
    import sys

    sys.path.insert(0, str(RACINE / "tools"))
    etude = _mod("etude_copiabilite")
    observe, publie = tmp_path / "a.jsonl.gz", tmp_path / "b.jsonl.gz"
    with gzip.open(observe, "wt", encoding="utf-8") as h:
        h.write(json.dumps({"coin": "BTC", "ts_ms": NOW, "funding": 0.00002, "mark": 1.0}) + "\n")
    with gzip.open(publie, "wt", encoding="utf-8") as h:
        h.write(json.dumps({"coin": "BTC", "ts_ms": NOW - HEURE, "funding": 0.00001, "interval": "1h"}) + "\n")
    shards = {"asset_ctx": [{"path": str(observe)}], "funding_history": [{"path": str(publie)}]}
    assert sorted(etude.load_funding(etude.funding_shards(shards))) == [("BTC", NOW - HEURE, 0.00001), ("BTC", NOW, 0.00002)]
    assert etude.funding_shards({"asset_ctx": [{"path": str(observe)}]}) == [{"path": str(observe)}]
