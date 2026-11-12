"""SOCLE DE COLLECTE FIABLE — plus de données SANS bannissement ni poubelle. On VERROUILLE :
dedup stable, cache borné, append/écriture atomiques, backoff avec jitter borné, limiteur de
débit, provenance, et porte de qualité (deny-by-default). Aucune donnée réseau."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from hl_observer.collection import collecte_fiable as C


# ─────────────── déduplication ───────────────

def test_cle_dedup_stable_et_discriminante():
    a = {"coin": "BTC", "ts": 1000, "x": 1}
    assert C.cle_dedup(a, ("coin", "ts")) == C.cle_dedup(dict(a), ("coin", "ts"))
    assert C.cle_dedup(a, ("coin", "ts")) != C.cle_dedup({"coin": "ETH", "ts": 1000}, ("coin", "ts"))


def test_cache_dedup_voit_neuf_une_fois_puis_non():
    c = C.CacheDedup()
    assert c.neuf("k1") is True and c.neuf("k1") is False


def test_cache_dedup_est_borne():
    c = C.CacheDedup(maximum=10)
    for i in range(50):
        c.neuf("k%d" % i)
    assert len(c._vus) <= 10


def test_filtrer_ne_garde_que_les_neufs():
    c = C.CacheDedup()
    enrs = [{"coin": "BTC", "ts": 1}, {"coin": "BTC", "ts": 1}, {"coin": "ETH", "ts": 1}]
    assert len(c.filtrer(enrs, ("coin", "ts"))) == 2


# ─────────────── écriture ───────────────

def test_append_jsonl_ecrit_et_cree_le_dossier(tmp_path):
    p = tmp_path / "sous" / "j.jsonl"
    n = C.append_jsonl(p, [{"a": 1}, {"a": 2}])
    lignes = p.read_text(encoding="utf-8").strip().splitlines()
    assert n == 2 and json.loads(lignes[1])["a"] == 2


def test_ecrire_atomique_ne_laisse_pas_de_tmp(tmp_path):
    p = tmp_path / "snap.json"
    C.ecrire_atomique(p, '{"ok": true}')
    assert p.read_text(encoding="utf-8") == '{"ok": true}'
    assert not list(tmp_path.glob(".snap.json.*.tmp"))


def test_ecrire_atomique_recupere_un_verrou_windows_transitoire(tmp_path, monkeypatch):
    p = tmp_path / "snap.json"
    remplacements = 0
    vrai_replace = C.os.replace

    def replace_transitoire(source: str | Path, cible: str | Path) -> None:
        nonlocal remplacements
        remplacements += 1
        if remplacements < 3:
            raise PermissionError(13, "verrou transitoire")
        vrai_replace(source, cible)

    monkeypatch.setattr(C.os, "replace", replace_transitoire)
    C.ecrire_atomique(p, '{"ok": true}', tentatives=3, delai_s=0)

    assert remplacements == 3
    assert p.read_text(encoding="utf-8") == '{"ok": true}'
    assert not list(tmp_path.glob(".snap.json.*.tmp"))


def test_ecrire_atomique_propage_un_verrou_persistant_sans_tmp(tmp_path, monkeypatch):
    p = tmp_path / "snap.json"
    p.write_text('{"avant": true}', encoding="utf-8")

    def replace_verrouille(_source: str | Path, _cible: str | Path) -> None:
        raise PermissionError(13, "verrou persistant")

    monkeypatch.setattr(C.os, "replace", replace_verrouille)
    with pytest.raises(PermissionError, match="verrou persistant"):
        C.ecrire_atomique(p, '{"apres": true}', tentatives=2, delai_s=0)

    assert p.read_text(encoding="utf-8") == '{"avant": true}'
    assert not list(tmp_path.glob(".snap.json.*.tmp"))


# ─────────────── politesse réseau ───────────────

def test_backoff_grandit_et_reste_borne():
    d0 = C.backoff_jitter(0, base_s=1.0, plafond_s=60.0)
    d5 = C.backoff_jitter(5, base_s=1.0, plafond_s=60.0)
    assert 0.7 <= d0 <= 1.3                              # ~1 s +/- jitter
    assert d5 <= 60.0 * 1.25 and d5 > d0                 # croit, plafonne


def test_limiteur_laisse_passer_puis_fait_attendre():
    lim = C.Limiteur(intervalle_s=10.0)
    assert lim.attente(maintenant=100.0) == 0.0          # 1re fois : prete
    assert lim.attente(maintenant=100.0) > 0.0           # 2e tout de suite : doit attendre


# ─────────────── provenance & qualité ───────────────

def test_estampiller_ajoute_provenance_et_read_only():
    e = C.estampiller({"coin": "BTC"}, source="hl_book", maintenant=1_700_000_000.0)
    assert e["source"] == "hl_book" and e["collecte_ts"] == 1_700_000_000.0
    assert e["read_only"] is True and e["real_execution"] is False


def test_qualite_rejette_prix_nul_ecart_aberrant_et_ts_vieux():
    bon = {"collecte_ts": 1_700_000_000.0, "px": 60000.0, "ecart_prix_bps": 20.0}
    assert C.qualite_ok(bon, champs_prix=("px",), ecart_bps_max=500.0) is True
    assert C.qualite_ok({**bon, "px": 0.0}, champs_prix=("px",)) is False           # prix nul
    assert C.qualite_ok({**bon, "ecart_prix_bps": 1e6}, ecart_bps_max=500.0) is False  # aberrant
    assert C.qualite_ok({**bon, "collecte_ts": 100.0}) is False                     # 1970, implausible


def test_collecter_proprement_estampille_filtre_et_dedoublonne():
    enrs = [{"coin": "BTC", "px": 60000.0, "ecart_prix_bps": 20.0},
            {"coin": "BTC", "px": 60000.0, "ecart_prix_bps": 20.0},   # doublon
            {"coin": "ETH", "px": 0.0, "ecart_prix_bps": 5.0}]         # prix nul -> rejete
    propres = C.collecter_proprement(enrs, source="hl", champs_cle=("coin", "ecart_prix_bps"),
                                     champs_prix=("px",), ecart_bps_max=500.0)
    assert len(propres) == 1 and propres[0]["coin"] == "BTC"
    assert propres[0]["source"] == "hl" and propres[0]["real_execution"] is False


def test_budget_partage_inactif_sans_variable(tmp_path, monkeypatch):
    monkeypatch.delenv(C.BUDGET_DEBIT_ENV, raising=False)
    assert C.reserver_poids(500.0, dormir=lambda s: 1 / 0) == 0.0          # jamais d'attente si inactif


def test_budget_partage_attend_borne_et_enregistre_la_consommation(tmp_path, monkeypatch):
    fichier = tmp_path / "budget.json"
    monkeypatch.setenv(C.BUDGET_DEBIT_ENV, str(fichier))
    t = [1000.0]
    siestes: list[float] = []

    def dormir(s):
        siestes.append(s)
        t[0] += s

    # sous le seuil : aucune attente, mais la consommation est enregistrée
    assert C.reserver_poids(300.0, maintenant=lambda: t[0], dormir=dormir) == 0.0
    assert siestes == [] and C._lire_fenetre_budget(fichier, t[0]) == [(1000.0, 300.0)]

    # on remplit presque le seuil (1000/min), puis une requête qui dépasse → attente bornée
    C.reserver_poids(650.0, maintenant=lambda: t[0], dormir=dormir)        # total 950
    siestes.clear()
    attente = C.reserver_poids(120.0, maintenant=lambda: t[0], dormir=dormir)   # 950+120 = 1070 > 1000
    assert 0 < attente <= C.ATTENTE_MAX_BUDGET_S and siestes == [attente]
    assert attente == pytest.approx(C.pause_pour_poids(70.0, budget_par_minute=C.SEUIL_POIDS_PARTAGE_PAR_MINUTE))
    # la consommation finale est bien enregistrée
    assert sum(w for _, w in C._lire_fenetre_budget(fichier, t[0])) == pytest.approx(1070.0)


def test_budget_partage_purge_la_fenetre_glissante(tmp_path, monkeypatch):
    fichier = tmp_path / "budget.json"
    monkeypatch.setenv(C.BUDGET_DEBIT_ENV, str(fichier))
    fichier.write_text(json.dumps([[100.0, 900.0]]), encoding="utf-8")       # vieil événement
    # 120 s plus tard : l'événement est hors fenêtre (60 s), donc aucune attente malgré 900
    assert C.reserver_poids(800.0, maintenant=lambda: 220.0, dormir=lambda s: 1 / 0) == 0.0


def test_budget_partage_deux_collecteurs_partagent_le_meme_fichier(tmp_path, monkeypatch):
    fichier = tmp_path / "budget.json"
    monkeypatch.setenv(C.BUDGET_DEBIT_ENV, str(fichier))
    now = 5000.0
    # deux « collecteurs » réservent tour à tour sur le MÊME fichier → le second voit la conso du premier
    C.reserver_poids(600.0, maintenant=lambda: now, dormir=lambda s: None)
    siestes: list[float] = []
    C.reserver_poids(600.0, maintenant=lambda: now, dormir=siestes.append)   # 600+600 = 1200 > 1000
    assert siestes and siestes[0] > 0                                        # le second attend à cause du premier


def test_budget_partage_fail_open_sur_fichier_corrompu(tmp_path, monkeypatch):
    fichier = tmp_path / "budget.json"
    monkeypatch.setenv(C.BUDGET_DEBIT_ENV, str(fichier))
    fichier.write_text("pas du json {", encoding="utf-8")
    # fichier illisible : on ne plante pas, on n'attend pas, et on réécrit une fenêtre saine
    assert C.reserver_poids(300.0, maintenant=lambda: 10.0, dormir=lambda s: None) == 0.0
    assert C._lire_fenetre_budget(fichier, 10.0) == [(10.0, 300.0)]


def test_budget_partage_vole_un_verrou_perime(tmp_path, monkeypatch):
    import os
    fichier = tmp_path / "budget.json"
    verrou = tmp_path / "budget.json.lock"
    verrou.write_text("mort", encoding="utf-8")
    os.utime(verrou, (0, 0))                                                 # verrou très vieux (périmé)
    monkeypatch.setenv(C.BUDGET_DEBIT_ENV, str(fichier))
    # le verrou périmé est volé : la réservation aboutit et le verrou est nettoyé
    assert C.reserver_poids(100.0, maintenant=lambda: 1.0, dormir=lambda s: None) == 0.0
    assert not verrou.exists() and C._lire_fenetre_budget(fichier, 1.0) == [(1.0, 100.0)]


def test_budget_partage_attente_jamais_au_dela_du_plafond(tmp_path, monkeypatch):
    fichier = tmp_path / "budget.json"
    monkeypatch.setenv(C.BUDGET_DEBIT_ENV, str(fichier))
    fichier.write_text(json.dumps([[1000.0, 999999.0]]), encoding="utf-8")   # fenêtre saturée à l'extrême
    attente = C.reserver_poids(500.0, maintenant=lambda: 1000.0, dormir=lambda s: None)
    assert attente == C.ATTENTE_MAX_BUDGET_S                                 # plafonnée, jamais infinie
