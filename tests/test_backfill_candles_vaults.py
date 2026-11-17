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


def test_refus_de_debit_on_RECULE_puis_on_renonce_et_un_echec_ne_bloque_pas_les_autres(tmp_path):
    """17/11/2026 — CONTRAT CHANGÉ, ET DURCI. L'ancien test s'appelait « on n'insiste pas » et
    exigeait `siestes == [ATTENTE_REFUS_S]` : une attente, un essai, arrêt. C'est ce contrat qui a
    coûté la passe de la nuit du 16 au 17/11 — arrêt après 37 minutes sur un refus, 334 minutes de
    budget inutilisées. La règle est maintenant celle du funding (`avec_recul`) : attentes qui
    S'ALLONGENT, abandon après `REFUS_AVANT_ABANDON` refus CONSÉCUTIFS seulement, et le nombre de
    refus est publié."""
    import urllib.error

    root = _racine(tmp_path, ["AAA", "BBB", "CCC"])

    def refuse(coin, intervalle, a, b):
        raise urllib.error.HTTPError("u", 429, "Too Many Requests", None, None)

    siestes = []
    bilan = BC.passe(root, intervalles=("1h",), now_ms=NOW, poster=refuse, dormir=siestes.append, univers=None)
    attendues = [BC.ATTENTE_REFUS_S * k for k in range(1, BC.REFUS_AVANT_ABANDON + 1)]
    assert bilan["arret"] == "LIMITE_DEBIT"
    assert siestes == attendues, "attentes croissantes, une par refus, ni plus ni moins"
    assert bilan["refus_consecutifs"] == BC.REFUS_AVANT_ABANDON
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
    # 15/11/2026 — 10 REQUETES, PAS 6 : la passe a DEUX fronts depuis le correctif de profondeur.
    # 6 pour prolonger (3 par coin : 500 + 500 + 301), puis 4 pour creuser — une page arriere par
    # coin, chacune suivie d'une SONDE depuis le plancher avant de conclure « plus rien avant ».
    # Le serveur de test ne publie rien avant `debut`, donc les deux coins sont declares au bout de
    # leur histoire et ne seront plus jamais redemandes.
    assert bilan["demandes"] == 10 and bilan["points"] == 2 * len(attendu) and bilan["arret"] is None
    assert bilan["origines"] == 2 and bilan["creuses"] == 0 and bilan["trous"] == []
    assert all(x["funding"] == 0.0000125 and x["interval"] == "1h" and x["source"] == "REST_FUNDING_HISTORY"
               and x["recv_ms"] == NOW for x in lignes)
    assert len(siestes) == 8 and all(s >= 2.0 for s in siestes)          # cadence respectée à chaque page
    # deux heures plus tard : deux points par coin, rien de réécrit
    appels.clear()
    encore = BC.passe_funding(root, now_ms=NOW + 2 * HEURE, poster=_serveur_funding(appels), dormir=siestes.append,
                              univers=None)
    assert encore["points"] == 4 and len(_lignes(root / BC.SORTIE_FUNDING)) == 2 * len(attendu) + 4
    # l'état des bougies et celui du funding cohabitent dans le même fichier sans s'écraser
    BC.passe(root, intervalles=("1h",), now_ms=NOW + 2 * HEURE, poster=_serveur([]), dormir=lambda s: None, univers=None)
    etat = json.loads((root / BC.ETAT).read_text(encoding="utf-8"))["intervalles"]
    assert set(etat) == {"1h", BC.SERIE_FUNDING, BC.SERIE_FUNDING_ANCIEN}
    assert set(etat[BC.SERIE_FUNDING]) == {"BTC", "xyz:XYZ100"}
    # Le front ARRIERE est une serie A PART, et c'est ce qui rend la profondeur rattrapable : la
    # serie historique ne portait que l'horodatage le plus RECENT, donc un coin « a jour » restait
    # a jamais a sa profondeur de depart.
    assert set(etat[BC.SERIE_FUNDING_ANCIEN]) == {"BTC", "xyz:XYZ100"}


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


# --------------------------------------------------------- --seulement-funding (14/11/2026)

def test_seulement_funding_ne_touche_PAS_aux_bougies(tmp_path, capsys):
    """POURQUOI CETTE OPTION. La passe bougies consomme ses 3 000 s AVANT que le funding n'obtienne
    ses 1 500 s, et le tout ne tourne que toutes les 4 h. Mesure du 14/11 : **90 coins ont du
    funding sur 261 suivis, 171 n'en ont JAMAIS eu**. Or la largeur de la section transversale joue
    sur les DEUX termes du rapport `brut/repli` qui fixe le resultat final.

    Ce test verrouille le fait que l'option saute bien la passe bougies : si elle la refaisait, elle
    ne servirait a rien, puisque c'est precisement le budget des bougies qui affame le funding.
    """
    m = _mod("backfill_candles_vaults")
    appels = {"bougies": 0, "funding": 0}

    def fausse_passe(*a, **k):
        appels["bougies"] += 1
        return {"coins": 1, "intervalles": {}, "arret": None, "coins_inconnus_non_demandes": []}

    def fausse_passe_funding(*a, **k):
        appels["funding"] += 1
        return {"points": 7, "demandes": 1, "a_jour": 0, "echecs": [], "arret": None}

    m.passe, m.passe_funding = fausse_passe, fausse_passe_funding
    assert m.main(["--root", str(tmp_path), "--seulement-funding"]) == 0
    assert appels == {"bougies": 0, "funding": 1}
    assert "funding 1h SEUL" in capsys.readouterr().out


def test_les_deux_options_contradictoires_sont_REFUSEES(tmp_path, capsys):
    """`--seulement-funding --sans-funding` demande de ne faire QUE le funding et PAS le funding.
    Executer silencieusement l'une des deux laisserait croire que la passe a fait son travail."""
    m = _mod("backfill_candles_vaults")
    m.passe = m.passe_funding = lambda *a, **k: (_ for _ in ()).throw(
        AssertionError("aucune passe ne doit etre lancee"))
    assert m.main(["--root", str(tmp_path), "--seulement-funding", "--sans-funding"]) == 2
    assert "contradictoires" in capsys.readouterr().out


def test_le_comportement_par_defaut_est_INCHANGE(tmp_path):
    """L'option ne doit rien changer quand elle n'est pas demandee : la campagne reexecute ce
    fichier toutes les 4 h."""
    m = _mod("backfill_candles_vaults")
    appels = {"bougies": 0, "funding": 0}
    def fausse_passe(*a, **k):
        appels["bougies"] += 1
        return {"coins": 1, "intervalles": {}, "arret": None, "coins_inconnus_non_demandes": []}
    def fausse_passe_funding(*a, **k):
        appels["funding"] += 1
        return {"points": 0, "demandes": 0, "a_jour": 1, "echecs": [], "arret": None}
    m.passe, m.passe_funding = fausse_passe, fausse_passe_funding
    assert m.main(["--root", str(tmp_path)]) == 0
    assert appels == {"bougies": 1, "funding": 1}


# ─────────────── 16/11 : l'etat ne doit plus TUER la passe sous Windows ───────────────
def test_un_remplacement_refuse_par_windows_est_RETENTE_et_non_fatal(tmp_path, monkeypatch):
    """`PermissionError: [WinError 5]` tuait la passe de backfill de la campagne.

    Cause : Windows refuse `os.replace` quand la CIBLE est ouverte, meme en lecture seule — et
    l'autre passe (campagne toutes les 4 h / rattrapage a la main) lit ce meme etat au debut de son
    propre `sauver_etat`. Elle ne le tient que quelques millisecondes.
    """
    import os as _os

    cible = tmp_path / "etat.json"
    tmp = tmp_path / "etat.json.tmp"
    tmp.write_text("{}", encoding="utf-8")
    essais = []
    vrai = _os.replace

    def refuse_deux_fois(src, dst):
        essais.append(1)
        if len(essais) < 3:
            raise PermissionError(5, "Acces refuse")
        return vrai(src, dst)

    monkeypatch.setattr(BC.os, "replace", refuse_deux_fois)
    siestes = []
    assert BC.remplacer_avec_patience(tmp, cible, dormir=siestes.append) is True
    assert len(essais) == 3 and cible.exists(), "le 3e essai doit passer, sans exception"
    assert siestes and all(s > 0 for s in siestes), "il faut ATTENDRE entre deux essais"


def test_un_refus_PERSISTANT_rend_False_au_lieu_de_perdre_la_passe(tmp_path, monkeypatch, capsys):
    cible = tmp_path / "etat.json"
    tmp = tmp_path / "etat.json.tmp"
    tmp.write_text("{}", encoding="utf-8")

    def toujours_refuse(src, dst):
        raise PermissionError(5, "Acces refuse")

    monkeypatch.setattr(BC.os, "replace", toujours_refuse)
    assert BC.remplacer_avec_patience(tmp, cible, dormir=lambda s: None) is False
    sortie = capsys.readouterr().out
    assert "etat NON sauve" in sortie and "ruban" in sortie, (
        "perdre un ETAT n'est pas perdre des DONNEES : il faut le dire, pas mourir")


def test_sauver_etat_ne_leve_plus_quand_le_remplacement_est_refuse(tmp_path, monkeypatch):
    """Le test qui compte : la passe continue. Une page d'etat perdue se resauve ; une passe tuee
    fait perdre des heures de requetes."""
    monkeypatch.setattr(BC, "remplacer_avec_patience", lambda tmp, cible, **kw: False)
    BC.sauver_etat(tmp_path, {"1h": {"BTC": 123}})      # ne doit pas lever


# ─────────── 16/11 : deux refus ne doivent plus tuer une passe de funding ───────────
def test_le_funding_RECULE_geometriquement_au_lieu_d_abandonner_au_deuxieme_refus(tmp_path):
    """Mesure du 16/11 : la passe s'est arrêtée sur LIMITE_DEBIT après 40 min, laissant
    **24 494 s de budget inutilisées**. L'AIMD existe pour reculer : chaque refus divise le débit
    par deux (600 -> 300 -> 150 -> 100, le plancher). Renoncer au deuxième refus, c'est abandonner
    avant même d'avoir atteint le débit prudent d'origine.
    """
    import urllib.error

    root = _racine(tmp_path, ["AAA"])
    appels = []
    bon = _serveur_funding(appels)
    refus = {"restants": 3}

    def refuse_puis_accepte(coin, a, b):
        if refus["restants"] > 0:
            refus["restants"] -= 1
            raise urllib.error.HTTPError("u", 429, "Too Many Requests", None, None)
        return bon(coin, a, b)

    siestes = []
    bilan = BC.passe_funding(root, now_ms=NOW, poster=refuse_puis_accepte,
                             dormir=siestes.append, univers=None)
    assert bilan["arret"] != "LIMITE_DEBIT", (
        "trois refus suivis d'un succes ne doivent pas arreter la passe : c'est exactement ce que "
        "l'AIMD est cense absorber")
    attentes = [s for s in siestes if s in (BC.ATTENTE_REFUS_S, 2 * BC.ATTENTE_REFUS_S,
                                            3 * BC.ATTENTE_REFUS_S)]
    assert attentes[:3] == [BC.ATTENTE_REFUS_S, 2 * BC.ATTENTE_REFUS_S, 3 * BC.ATTENTE_REFUS_S], (
        f"les attentes doivent CROITRE a chaque refus, obtenu {attentes[:3]}")


def test_une_venue_durablement_fermee_arrete_quand_meme_la_passe(tmp_path):
    """On recule, on ne s'acharne pas : au-delà de `REFUS_AVANT_ABANDON`, on rend la main."""
    import urllib.error

    root = _racine(tmp_path, ["AAA"])

    def refuse_toujours(coin, a, b):
        raise urllib.error.HTTPError("u", 429, "Too Many Requests", None, None)

    siestes = []
    bilan = BC.passe_funding(root, now_ms=NOW, poster=refuse_toujours,
                             dormir=siestes.append, univers=None)
    assert bilan["arret"] == "LIMITE_DEBIT"
    assert bilan.get("refus_consecutifs") == BC.REFUS_AVANT_ABANDON, (
        f"on doit abandonner APRES {BC.REFUS_AVANT_ABANDON} refus consecutifs, "
        f"pas avant : {bilan.get('refus_consecutifs')}")
