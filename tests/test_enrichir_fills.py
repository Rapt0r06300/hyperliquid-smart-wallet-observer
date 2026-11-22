"""Tests de l'enrichissement des fills avec contexte (pur, hors-ligne)."""
from __future__ import annotations

import json
import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE / "tools"))

import enrichir_fills as E  # noqa: E402

NOW = 1_800_000_000_000


def test_plus_proche_causal_pas_de_futur():
    idx = E.construire_index([
        {"coin": "ETH", "received_at_ms": NOW - 2000, "bid": "1990", "ask": "2010"},
        {"coin": "ETH", "received_at_ms": NOW + 5000, "bid": "2100", "ask": "2110"},  # futur
    ])
    r, lag = E.plus_proche(idx, "ETH", NOW, 60_000, causal=True)
    assert r is not None and r["received_at_ms"] == NOW - 2000 and lag == 2000  # pas le futur


def test_plus_proche_hors_lag():
    idx = E.construire_index([{"coin": "ETH", "received_at_ms": NOW - 120_000, "bid": "1", "ask": "2"}])
    r, _ = E.plus_proche(idx, "ETH", NOW, 60_000)
    assert r is None


def test_enrichir_fill_contexte():
    idx_bbo = E.construire_index([{"coin": "ETH", "received_at_ms": NOW - 1000, "bid": "1998", "ask": "2002"}])
    idx_fund = E.construire_index([{"coin": "ETH", "time": NOW - 10_000, "funding": "0.0001"}])
    idx_candle = E.construire_index([{"coin": "ETH", "open_ts_ms": NOW - 30_000, "open": "2000",
                                      "high": "2020", "low": "1990", "close": "2000"}])
    fill = {"coin": "ETH", "px": "2004", "sz": "1", "signe": 1, "ts_ms": NOW}
    e = E.enrichir_fill(fill, idx_bbo=idx_bbo, idx_funding=idx_fund, idx_candle=idx_candle)
    c = e["contexte"]
    assert c["apparie_carnet"] is True and c["mid_at_fill"] == 2000.0
    assert round(c["spread_bps"], 1) == 20.0
    assert round(c["slippage_bps"], 1) == 20.0        # acheté 2004 vs mid 2000 => +20 bps
    assert c["funding_rate"] == 0.0001
    assert round(c["realized_vol_bps"], 0) == 150.0   # (2020-1990)/2000


def test_enrichir_bout_en_bout(tmp_path):
    fills = tmp_path / "fills.jsonl"
    fills.write_text("\n".join(json.dumps(f) for f in [
        {"coin": "ETH", "px": "2004", "sz": "1", "signe": 1, "ts_ms": NOW},
        {"coin": "BTC", "px": "50000", "sz": "0.1", "signe": -1, "ts_ms": NOW},  # pas de carnet BTC
    ]), encoding="utf-8")
    bbo = tmp_path / "bbo.jsonl"
    bbo.write_text(json.dumps({"coin": "ETH", "received_at_ms": NOW - 500, "bid": "1999", "ask": "2001"}),
                   encoding="utf-8")
    out = tmp_path / "out.jsonl"
    rap = E.enrichir(fills, out, bbo_path=bbo)
    assert rap["fills"] == 2 and rap["apparies_carnet"] == 1 and rap["taux_appariement"] == 0.5
    lignes = [json.loads(x) for x in out.read_text(encoding="utf-8").splitlines() if x.strip()]
    assert lignes[0]["contexte"]["apparie_carnet"] is True
    assert lignes[1]["contexte"]["apparie_carnet"] is False


# ------------------------------- marqueur TWAP (mesure du 21/11/2026)
def test_un_fill_de_tranche_twap_est_marque_avec_son_groupe(tmp_path):
    """Sur 20 000 lignes du ruban reel, 14 champs decisifs sur 15 etaient presents.

    Le quinzieme manquait : rien ne disait qu'un fill est une tranche TWAP. Le labo
    lisait donc vingt tranches d'une meme decision comme vingt signaux independants.
    """
    fills = [
        {"vault": "0xaa", "coin": "BTC", "px": 100.0, "sz": 1.0, "ts_ms": 1_700_000_000_000,
         "tid": 11, "signe": 1},
        {"vault": "0xaa", "coin": "ETH", "px": 50.0, "sz": 2.0, "ts_ms": 1_700_000_000_100,
         "tid": 99, "signe": 1},
    ]
    # Ruban NORMALISE de la lane contexte : `twap_id` a plat.
    twap = [{"vault": "0xaa", "coin": "BTC", "tid": 11, "twap_id": 4242,
             "ts_ms": 1_700_000_000_000}]
    f = tmp_path / "fills.jsonl"
    t = tmp_path / "twap.jsonl"
    f.write_text("\n".join(json.dumps(x) for x in fills) + "\n", encoding="utf-8")
    t.write_text("\n".join(json.dumps(x) for x in twap) + "\n", encoding="utf-8")
    sortie = tmp_path / "enrichi.jsonl"

    rapport = E.enrichir(f, sortie, twap_path=t)
    assert rapport["tranches_twap"] == 1
    assert rapport["twap_connu"] is True
    lignes = [json.loads(ligne)
              for ligne in sortie.read_text(encoding="utf-8").splitlines()
              if ligne.strip()]
    assert lignes[0]["contexte"]["twap"] is True
    assert lignes[0]["contexte"]["twap_id"] == 4242
    # Le fill qui n'est pas une tranche est marque FAUX, pas inconnu : le ruban etait la.
    assert lignes[1]["contexte"]["twap"] is False
    assert lignes[1]["contexte"]["twap_id"] is None


def test_sans_ruban_twap_le_marqueur_dit_INCONNU_et_non_NON(tmp_path):
    """Confondre `None` et `False` ferait passer une ignorance pour une observation."""
    f = tmp_path / "fills.jsonl"
    f.write_text(json.dumps({"vault": "0xaa", "coin": "BTC", "px": 1.0, "sz": 1.0,
                             "ts_ms": 1_700_000_000_000, "tid": 11}) + "\n", encoding="utf-8")
    sortie = tmp_path / "enrichi.jsonl"
    rapport = E.enrichir(f, sortie)
    assert rapport["twap_connu"] is False
    ligne = json.loads(sortie.read_text(encoding="utf-8").splitlines()[0])
    assert ligne["contexte"]["twap"] is None
    assert ligne["contexte"]["twap_source"] == "ruban_twap_absent"


def test_la_forme_brute_d_hyperliquid_est_aussi_indexee():
    """`{"twapId": .., "fill": {..}}` : la reponse officielle, sans normalisation."""
    index = E.index_twap_du_ruban([
        {"twapId": 7, "fill": {"tid": 1, "hash": "0xa", "oid": 5}},
        {"twap_id": 8, "fill": {"tid": 2}},
        {"fill": {"tid": 3}},                 # sans identifiant : n'entre pas dans l'index
    ])
    assert index[1] == 7 and index["0xa"] == 7 and index[5] == 7
    assert index[2] == 8
    assert 3 not in index, "un TWAP sans identifiant ne doit pas creer de groupe"


def test_un_identifiant_absent_ne_fabrique_jamais_de_groupe():
    """Un `0` ou un groupe par defaut fusionnerait des TWAP differents."""
    assert E.marquer_twap({"tid": 1}, {}) == (None, None)
    assert E.marquer_twap({"tid": 1}, {2: 9}) == (False, None)
    assert E.marquer_twap({"tid": 1}, {1: 9}) == (True, 9)
