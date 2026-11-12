"""Backfill CLI userFillsByTime (rectif Flo 23/07) : cibles = retenus + témoin (deny-by-default si pas
de score), pagination + parsing + dédup d'UN vault avec poster INJECTÉ (aucun réseau)."""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]


def _mod(nom: str):
    spec = importlib.util.spec_from_file_location(nom, RACINE / "tools" / f"{nom}.py")
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


BF = _mod("backfill_vault_fills")


def test_vaults_cibles_retenus_et_temoin(tmp_path):
    (tmp_path / "runtime" / "data").mkdir(parents=True)
    (tmp_path / "runtime" / "data" / "vaults_scores.json").write_text(json.dumps({
        "retenus": ["0xR1", "0xR2"],
        "classement": [{"vault": "0xR1", "retenu": True}, {"vault": "0xN1", "retenu": False},
                       {"vault": "0xN2", "retenu": False}]}))
    retenus, temoin = BF.vaults_cibles(tmp_path)
    assert retenus == ["0xR1", "0xR2"] and temoin == ["0xN1", "0xN2"]
    assert BF.vaults_cibles(tmp_path / "vide") == ([], [])            # pas de score -> deny-by-default


def test_backfill_un_vault_pagine_parse_dedup(tmp_path):
    from hl_observer.collection import collecte_fiable as CF
    appels = {"n": 0}

    def faux_poster(vault, a, b):
        appels["n"] += 1
        row = {"time": a, "coin": "SOL", "px": "150", "sz": "10", "side": "B",
               "dir": "Open Long", "startPosition": "0", "oid": 1}
        return [row, dict(row)]

    fills = BF.backfill_un_vault(tmp_path, "0xR1", lookback_j=2, limiteur=CF.Limiteur(0.0), poster=faux_poster)
    assert appels["n"] == 2
    assert len(fills) == 2 and all(row["coin"] == "SOL" for row in fills)
    assert len({row["ts_ms"] for row in fills}) == 2


# ------------------------------------------------------------------ historique des leaders lents (incrémental)

JOUR = 86_400_000
L1, L2 = "0x" + "1" * 40, "0x" + "2" * 40


def _serveur_leaders(appels, fills_par_leader):
    """Faux ``userFillsByTime`` : rend les fills du leader dont l'instant tombe dans la fenêtre demandée."""
    def poster(vault, a, b):
        appels.append((vault, a, b))
        return [f for f in fills_par_leader.get(vault, []) if a <= f["time"] <= b]
    return poster


def _fill_api(t, tid, *, crossed=True, coin="xyz:XYZ100"):
    return {"time": t, "coin": coin, "px": "100", "sz": "2", "side": "B", "dir": "Open Long",
            "startPosition": "0", "tid": tid, "oid": tid, "hash": f"0x{tid:x}", "crossed": crossed, "fee": "0.01"}


def _ruban(root):
    chemin = root / BF.OUT_FILLS_LEADERS
    return [json.loads(x) for x in chemin.read_text(encoding="utf-8").splitlines()] if chemin.is_file() else []


def test_leaders_lents_premier_passage_profond_puis_seulement_les_fills_nouveaux(tmp_path):
    from hl_observer.collection import collecte_fiable as CF

    now = 1_790_000_000_000
    fills = {L1: [_fill_api(now - 150 * JOUR, 1), _fill_api(now - 3 * JOUR, 2, crossed=False)],
             L2: [_fill_api(now - 10 * JOUR, 3)]}
    appels: list = []
    limiteur = CF.Limiteur(0.0)
    import time as _time
    reel = _time.time
    try:
        _time.time = lambda: now / 1000.0                       # l'outil date ses fenêtres à l'horloge murale
        bilan = BF.backfill_leaders_lents(tmp_path, limiteur=limiteur, leaders=[L1, L2], now_ms=now,
                                          poster=_serveur_leaders(appels, fills))
        assert bilan["traites"] == 2 and bilan["complets"] == 2 and bilan["fills_ajoutes"] == 3 and not bilan["arret"]
        lignes = _ruban(tmp_path)
        assert [(x["vault"], x["tid"], x["crossed"], x["groupe"]) for x in lignes] == [
            (L1, 1, True, "LEADER_LENT"), (L1, 2, False, "LEADER_LENT"), (L2, 3, True, "LEADER_LENT")]
        assert all(x["coin"] == "xyz:XYZ100" and x["fee"] == "0.01" for x in lignes)      # identité native, frais gardés
        # pagination au curseur : un leader lent ne coûte qu'UNE requête pour 200 jours
        assert len(appels) == 2 and bilan["pages"] == 2
        assert all(a == now - BF.LOOKBACK_LEADERS_J * JOUR and b == now for _, a, b in appels)
        # le lendemain : un fill de plus pour L1 ; seul celui-là est ajouté, sur une fenêtre courte
        fills[L1].append(_fill_api(now + JOUR // 2, 4))
        appels.clear()
        _time.time = lambda: (now + JOUR) / 1000.0
        bilan = BF.backfill_leaders_lents(tmp_path, limiteur=limiteur, leaders=[L1, L2], now_ms=now + JOUR,
                                          poster=_serveur_leaders(appels, fills))
        assert bilan["fills_ajoutes"] == 1 and [x["tid"] for x in _ruban(tmp_path)] == [1, 2, 3, 4]
        assert all(b - a <= 12 * JOUR for _, a, b in appels) and len(appels) == 2   # plus jamais les 200 jours
        # rejoué au même instant : rien n'est réécrit (idempotent)
        bilan = BF.backfill_leaders_lents(tmp_path, limiteur=limiteur, leaders=[L1, L2], now_ms=now + JOUR,
                                          poster=_serveur_leaders(appels, fills))
        assert bilan["fills_ajoutes"] == 0 and len(_ruban(tmp_path)) == 4
    finally:
        _time.time = reel


def test_leaders_lents_une_panne_ne_fait_pas_avancer_le_curseur_et_le_budget_fait_tourner(tmp_path):
    import urllib.error

    from hl_observer.collection import collecte_fiable as CF

    now = 1_790_000_000_000
    fills = {L1: [_fill_api(now - 5 * JOUR, 1)], L2: [_fill_api(now - 6 * JOUR, 2)]}
    bon = _serveur_leaders([], fills)

    def en_panne(vault, a, b):
        if vault == L1:
            raise urllib.error.URLError("coupure")
        return bon(vault, a, b)

    import time as _time
    reel = _time.time
    try:
        _time.time = lambda: now / 1000.0
        bilan = BF.backfill_leaders_lents(tmp_path, limiteur=CF.Limiteur(0.0), leaders=[L1, L2], now_ms=now,
                                          poster=en_panne)
        assert bilan["incomplets"] == [L1] and bilan["complets"] == 1
        etat = json.loads((tmp_path / BF.ETAT_LEADERS).read_text(encoding="utf-8"))["leaders"]
        assert not etat[L1].get("dernier_ts_ms") and etat[L2]["dernier_ts_ms"] == now - 6 * JOUR
        # la panne passée, la période entière est redemandée : aucun trou silencieux
        bilan = BF.backfill_leaders_lents(tmp_path, limiteur=CF.Limiteur(0.0), leaders=[L1, L2], now_ms=now,
                                          poster=bon)
        assert sorted(x["tid"] for x in _ruban(tmp_path)) == [1, 2] and bilan["incomplets"] == []
        # budget de temps épuisé après un leader : le suivant passera d'abord au prochain passage
        (tmp_path / BF.ETAT_LEADERS).unlink()
        (tmp_path / BF.OUT_FILLS_LEADERS).unlink()
        tic = iter(range(0, 100_000, 3_000))
        court = BF.backfill_leaders_lents(tmp_path, limiteur=CF.Limiteur(0.0), leaders=[L1, L2], now_ms=now, poster=bon,
                                          budget_s=4_000.0, horloge=lambda: next(tic))
        assert court["arret"] == "BUDGET_DE_TEMPS" and court["traites"] == 1
        suite = BF.backfill_leaders_lents(tmp_path, limiteur=CF.Limiteur(0.0), leaders=[L1, L2], now_ms=now + 1_000,
                                          poster=bon, max_leaders=1)
        assert suite["traites"] == 1 and sorted(x["vault"] for x in _ruban(tmp_path)) == [L1, L2]
    finally:
        _time.time = reel


def test_leaders_lents_ruban_connu_du_certificateur_et_du_registre():
    import sys

    sys.path.insert(0, str(RACINE / "src"))
    from hl_observer.datasets import coffre_certifie as C
    from hl_observer.datasets import couverture_donnees as R

    assert C._FICHIERS_CONNUS["leader_fills_backfill.jsonl"] == (C.FAMILLE_FILLS_BACKFILL, "REST_BACKFILL")
    flux = next(f for f in R.FLUX if f.fichier == "leader_fills_backfill.jsonl")
    assert flux.famille == "fills_backfill" and flux.labo == R.CONSOMME and "--ouvertures" in flux.usage
    assert BF.backfill_leaders_lents(RACINE / "inexistant", limiteur=None, leaders=[])["traites"] == 0


def test_leaders_lents_un_compte_trop_actif_est_marque_puis_laisse_de_cote(tmp_path):
    from hl_observer.collection import collecte_fiable as CF

    now = 1_790_000_000_000
    # L1 rend toujours une page pleine : il a plus de fills que le quota de pages n'en couvre
    def poster(vault, a, b):
        if vault == L1:
            return [_fill_api(a + 1 + i, 10_000 + (a % 1_000_000) * 3 + i) for i in range(BF.VB.CAP_USERFILLS)]
        return [_fill_api(now - 5 * JOUR, 2)] if a <= now - 5 * JOUR <= b else []

    import time as _time
    reel = _time.time
    try:
        _time.time = lambda: now / 1000.0
        bilan = BF.backfill_leaders_lents(tmp_path, limiteur=CF.Limiteur(0.0), leaders=[L1, L2], now_ms=now,
                                          poster=poster, max_pages_par_leader=3)
        assert bilan["trop_actifs"] == 1 and bilan["complets"] == 1 and bilan["incomplets"] == []
        etat = json.loads((tmp_path / BF.ETAT_LEADERS).read_text(encoding="utf-8"))["leaders"]
        assert etat[L1]["trop_actif"] is True and not etat[L1].get("dernier_ts_ms") and etat[L2]["complet"] is True
        # au passage suivant il n'est plus redemandé : aucune requête pour lui
        vus: list = []

        def espion(vault, a, b):
            vus.append(vault)
            return poster(vault, a, b)

        suite = BF.backfill_leaders_lents(tmp_path, limiteur=CF.Limiteur(0.0), leaders=[L1, L2], now_ms=now + JOUR,
                                          poster=espion, max_pages_par_leader=3)
        assert L1 not in vus and suite["trop_actifs"] == 1 and suite["traites"] == 1
        # quota relevé : il est redemandé une fois (un quota trop bas ne condamne pas un leader pour toujours)
        vus.clear()
        BF.backfill_leaders_lents(tmp_path, limiteur=CF.Limiteur(0.0), leaders=[L1, L2], now_ms=now + 2 * JOUR,
                                  poster=espion, max_pages_par_leader=4)
        assert L1 in vus
        # et jamais une couverture partielle : rien n'a été écrit pour le leader trop actif
        assert {x["vault"] for x in _ruban(tmp_path)} == {L2}
    finally:
        _time.time = reel


def test_pagination_au_curseur_pages_pleines_jointure_dedupliquee_et_blocage_declare(tmp_path):
    """Forme réelle vérifiée le 2026-11-11 : fills par instant croissant, page pleine = les plus anciens."""
    from hl_observer.collection import collecte_fiable as CF

    now = 1_790_000_000_000
    cap = BF.VB.CAP_USERFILLS
    tous = [_fill_api(now - 100 * JOUR + i * 60_000, i + 1) for i in range(2 * cap + 500)]     # 4 500 fills
    tous[cap] = dict(tous[cap], time=tous[cap - 1]["time"])                                     # deux fills au même instant, à la jointure

    def serveur(vault, a, b):
        return [f for f in tous if a <= f["time"] <= b][:cap]

    appels: list = []

    def espion(vault, a, b):
        appels.append(a)
        return serveur(vault, a, b)

    bilan = BF.backfill_leaders_lents(tmp_path, limiteur=CF.Limiteur(0.0), leaders=[L1], now_ms=now, poster=espion)
    assert bilan["complets"] == 1 and bilan["pages"] == 3 and len(appels) == 3
    lignes = _ruban(tmp_path)
    assert len(lignes) == len(tous) and len({x["tid"] for x in lignes}) == len(tous)             # ni trou ni doublon
    # une page pleine d'un seul instant : impossible d'avancer sans risquer un trou -> déclaré incomplet
    meme = [_fill_api(now - JOUR, 10_000 + i) for i in range(cap)]
    bloque = BF.backfill_leaders_lents(tmp_path / "b", limiteur=CF.Limiteur(0.0), leaders=[L2], now_ms=now,
                                       poster=lambda v, a, b: meme)
    assert bloque["incomplets"] == [L2] and bloque["complets"] == 0
    etat = json.loads((tmp_path / "b" / BF.ETAT_LEADERS).read_text(encoding="utf-8"))["leaders"][L2]
    assert etat["pagination"] == "BLOQUE_MEME_INSTANT" and not etat.get("dernier_ts_ms")


def test_vaults_retenus_pagines_au_curseur_avec_un_recu_d_audit_honnete(tmp_path, monkeypatch):
    """90 requêtes par vault (une par jour) rendaient le passage impraticable : une requête par 2 000 fills."""
    from hl_observer.collection import collecte_fiable as CF

    monkeypatch.setattr(BF.VB, "CAP_USERFILLS", 3)
    monkeypatch.setattr(BF.time, "sleep", lambda s: None)
    now = 1_794_000_000_000
    vault = "0x" + "c" * 40
    tous = [_fill_api(now - 5 * JOUR + i * 1_000, i) for i in range(7)]
    appels: list[tuple[int, int]] = []

    def serveur(v, a, b):
        appels.append((a, b))
        return [f for f in tous if a <= f["time"] <= b][:3]

    def page(fills, audit):
        return len(fills), audit["complete"], audit["requested_windows"], audit["partial_reasons"]

    fills, audit = BF.backfill_un_vault_au_curseur_avec_audit(
        tmp_path, vault, lookback_j=90, limiteur=CF.Limiteur(0.0), poster=serveur, now_ms=now)
    assert page(fills, audit) == (7, True, 4, []) and audit["pagination"] == "CURSEUR_CROISSANT"
    assert appels[0] == (now - 90 * JOUR, now) and [a for a, _ in appels[1:]] == [tous[2]["time"], tous[4]["time"],
                                                                                 tous[6]["time"]]
    assert audit["coverage_status"] == "COMPLETE_FOR_REQUESTED_RANGE" and audit["pending_window_ranges"] == []
    assert audit["usable_horizon"]["start_ms"] == tous[0]["time"] and audit["n_fills"] == 7

    # quota de pages épuisé : jamais déclaré complet, et la suite à demander est dite
    fills, audit = BF.backfill_un_vault_au_curseur_avec_audit(
        tmp_path, vault, lookback_j=90, limiteur=CF.Limiteur(0.0), poster=serveur, now_ms=now, max_pages=2)
    assert page(fills, audit)[1:] == (False, 2, ["MAX_PAGES_REACHED"]) and audit["request_budget_exhausted"] is True
    assert audit["pending_window_ranges"] == [{"start_ms": tous[4]["time"], "end_ms": now}]

    # panne réseau : partiel
    def en_panne(v, a, b):
        raise OSError("réseau coupé")

    fills, audit = BF.backfill_un_vault_au_curseur_avec_audit(
        tmp_path, vault, lookback_j=90, limiteur=CF.Limiteur(0.0), poster=en_panne, now_ms=now)
    assert page(fills, audit) == (0, False, 0, ["PAGINATION_ERROR"]) and audit["status"] == "PARTIAL"

    # rétention publique atteinte : le début de la période est censuré, jamais « complet »
    monkeypatch.setattr(BF.VB, "RETENTION_USERFILLS", 7)
    fills, audit = BF.backfill_un_vault_au_curseur_avec_audit(
        tmp_path, vault, lookback_j=90, limiteur=CF.Limiteur(0.0), poster=serveur, now_ms=now)
    assert audit["complete"] is False and audit["partial_reasons"] == ["PUBLIC_RETENTION_LIMIT_REACHED"]

    # ligne illisible dans une réponse : comptée, et le reçu n'est pas complet
    monkeypatch.setattr(BF.VB, "RETENTION_USERFILLS", 10_000)
    fills, audit = BF.backfill_un_vault_au_curseur_avec_audit(
        tmp_path, vault, lookback_j=90, limiteur=CF.Limiteur(0.0), poster=lambda v, a, b: [tous[0], "illisible"],
        now_ms=now)
    assert len(fills) == 1 and audit["complete"] is False and "INVALID_FILL_ROWS" in audit["partial_reasons"]


def test_le_passage_des_vaults_retenus_demande_peu_de_requetes(tmp_path, monkeypatch):
    """Un vault ordinaire : une page de fills et UNE fenêtre de dépôts/retraits (182 requêtes auparavant)."""
    monkeypatch.setattr(BF.time, "sleep", lambda s: None)
    vault = "0x" + "d" * 40
    (tmp_path / "runtime" / "data").mkdir(parents=True)
    (tmp_path / BF.SCORES).write_text(json.dumps({"retenus": [vault], "classement": []}), encoding="utf-8")
    demandes = {"fills": [], "ledger": []}
    now = BF.time.time() * 1000

    def fills(v, a, b):
        demandes["fills"].append((a, b))
        return [_fill_api(int(now) - JOUR, 1)]

    def ledger(v, a, b):
        demandes["ledger"].append((a, b))
        return []

    monkeypatch.setattr(BF, "_post_userfills", fills)
    monkeypatch.setattr(BF, "_post_ledger", ledger)
    monkeypatch.setattr(BF.backfill_un_vault_au_curseur_avec_audit, "__kwdefaults__",
                        {**BF.backfill_un_vault_au_curseur_avec_audit.__kwdefaults__, "poster": fills})
    monkeypatch.setattr(BF.backfill_ledger_un_vault_avec_audit, "__kwdefaults__",
                        {**BF.backfill_ledger_un_vault_avec_audit.__kwdefaults__, "poster": ledger})
    assert BF.main(["--root", str(tmp_path), "--sans-leaders"]) == 0
    assert len(demandes["fills"]) == 1 and len(demandes["ledger"]) == 1
    debut, fin = demandes["ledger"][0]
    assert fin - debut >= 89 * JOUR                                                    # toute la période, d'un coup
    couverture = json.loads((tmp_path / BF.OUT_COUVERTURE).read_text(encoding="utf-8"))
    assert couverture["backfill_complete"] is True and couverture["backfill_fill_audits"][0]["pagination"] == "CURSEUR_CROISSANT"
