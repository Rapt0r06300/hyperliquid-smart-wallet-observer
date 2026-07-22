"""SOCLE DE COLLECTE FIABLE — plus de données SANS bannissement ni poubelle. On VERROUILLE :
dedup stable, cache borné, append/écriture atomiques, backoff avec jitter borné, limiteur de
débit, provenance, et porte de qualité (deny-by-default). Aucune donnée réseau."""
from __future__ import annotations

import json

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
    assert not (tmp_path / "snap.json.tmp").exists()


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
