"""Test du chargement du tier LOCAL du coffre-fort pour la recherche du labo."""
from __future__ import annotations

import gzip
import hashlib
import json
import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE / "src"))

from hl_observer.backtesting.copy_vault_local_lab import _charger_tier_local  # noqa: E402


def _ecrire_shard(root: Path, famille: str, rows: list[dict], nom: str = "lot__x") -> str:
    rel = f"runtime/coffre_certifie/local/shards/{famille}/{nom}.jsonl.gz"
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    with gzip.open(p, "wt", encoding="utf-8") as h:
        for r in rows:
            h.write(json.dumps(r) + "\n")
    return rel


def _index(root: Path, entrees: list[dict]) -> None:
    coffre = root / "runtime" / "coffre_certifie"
    coffre.mkdir(parents=True, exist_ok=True)
    (coffre / "LOCAL_INDEX.json").write_text(json.dumps({"shards": entrees}), encoding="utf-8")


def _sha(root: Path, rel: str) -> str:
    return hashlib.sha256((root / rel).read_bytes()).hexdigest()


def test_charge_fills_causaux_tagues(tmp_path):
    root = tmp_path
    rows = [{"vault": "0xabc", "coin": "ETH", "px": 2000.0, "sz": 1.0, "signe": 1,
             "ts_ms": 1799999999000, "source": "LIVE_POLL", "isSnapshot": False,
             "observed_at_ms": 1799999999500} for _ in range(3)]
    rel = _ecrire_shard(root, "fills_forward", rows)
    _index(root, [{"famille": "fills_forward", "shard": rel, "sha256": _sha(root, rel)}])

    res = _charger_tier_local(root)
    assert res["statut"] == "OK" and res["fills_causaux"] == 3
    assert len(res["_fills"]) == 3 and all(r["provenance_tier"] == "LOCAL" for r in res["_fills"])
    # jamais de quality=SAFE -> ne peut pas etre "prouve"
    assert all(r.get("quality") != "SAFE" and r.get("source_quality_status") != "SAFE"
               for r in res["_fills"])


def test_rejette_sha_altere(tmp_path):
    root = tmp_path
    rel = _ecrire_shard(root, "fills_forward", [{"vault": "0x1", "coin": "ETH", "px": 1.0,
                        "sz": 1.0, "signe": 1, "ts_ms": 1, "source": "LIVE_POLL", "isSnapshot": False}])
    _index(root, [{"famille": "fills_forward", "shard": rel, "sha256": "0" * 64}])  # SHA faux
    res = _charger_tier_local(root)
    assert res["shards_rejetes"] == 1 and res["_fills"] == []


def test_absent_si_pas_de_coffre(tmp_path):
    assert _charger_tier_local(tmp_path)["statut"] == "ABSENT"


def test_classe_fills_books_bbo(tmp_path):
    root = tmp_path
    r_fill = _ecrire_shard(root, "fills_forward", [{"vault": "0x1", "coin": "ETH", "ts_ms": 10,
                           "source": "LIVE_POLL", "isSnapshot": False, "px": 1.0, "sz": 1.0, "signe": 1}])
    r_l2 = _ecrire_shard(root, "book_l2", [{"coin": "ETH", "received_at_ms": 20, "exchange_ts_ms": 10,
                         "bid": 1.0, "ask": 2.0, "bids5": [[1.0, 1.0]], "asks5": [[2.0, 1.0]]}])
    r_bbo = _ecrire_shard(root, "bbo", [{"coin": "ETH", "received_at_ms": 20, "exchange_ts_ms": 10,
                          "bid_px": 1.0, "ask_px": 2.0, "bid_sz": 1.0, "ask_sz": 1.0}])
    _index(root, [
        {"famille": "fills_forward", "shard": r_fill, "sha256": _sha(root, r_fill)},
        {"famille": "book_l2", "shard": r_l2, "sha256": _sha(root, r_l2)},
        {"famille": "bbo", "shard": r_bbo, "sha256": _sha(root, r_bbo)},
    ])
    res = _charger_tier_local(root)
    assert res["fills_causaux"] == 1 and res["carnets"] == 1 and res["bbo"] == 1
    assert len(res["_books"]) == 1 and len(res["_bbo"]) == 1


def test_snapshot_non_compte_comme_causal(tmp_path):
    root = tmp_path
    # un fill snapshot/liquidation : present mais PAS compte comme causal
    rel = _ecrire_shard(root, "fills_forward", [{"vault": "0x1", "coin": "ETH", "ts_ms": 10,
                        "source": "userFills.liquidation", "isSnapshot": None, "px": 1.0, "sz": 1.0, "signe": 1}])
    _index(root, [{"famille": "fills_forward", "shard": rel, "sha256": _sha(root, rel)}])
    res = _charger_tier_local(root)
    assert res["fills_causaux"] == 0 and len(res["_fills"]) == 1  # present mais non causal


def test_cotations_du_collecteur_bbo_adaptees_a_la_forme_du_labo(tmp_path):
    """Le BBO Hyperliquid du collecteur (bid/ask/ts_ex) sert au labo : memes grandeurs, autres noms."""
    root = tmp_path
    base = {"venue": "HL", "type_ligne": "QUOTE", "coin": "BTC", "bid": 100.0, "ask": 100.5,
            "bid_sz": 2.0, "ask_sz": 3.0, "recv_wall_ts_ms": 5_000, "ts_ex": 4_900.0}
    rows = [
        base,
        {**base, "recv_wall_ts_ms": 5_400, "ts_ex": 5_300.0},             # meme seconde : non retenue
        {**base, "recv_wall_ts_ms": 6_000, "ts_ex": 5_950.0, "bid": 101.0, "ask": 101.5},
        {**base, "recv_wall_ts_ms": 7_000, "ts_ex": 6_900.0, "bid": 102.0, "ask": 101.0},   # croise
        {**base, "recv_wall_ts_ms": 8_000, "ts_ex": 9_000.0},             # bourse apres reception
        {**base, "recv_wall_ts_ms": 9_000, "ts_ex": 8_900.0, "bid_sz": None},               # sans taille
        {**base, "venue": "BIN_TRADE", "type_ligne": "TRADE", "recv_wall_ts_ms": 10_000},   # autre venue
        {"venue": "HL", "type_ligne": "QUOTE", "coin": "ETH", "bid": True, "ask": 2.0,
         "bid_sz": 1.0, "ask_sz": 1.0, "recv_wall_ts_ms": 11_000, "ts_ex": 10_900.0},       # booleen
    ]
    rel = _ecrire_shard(root, "bbo", rows)
    _index(root, [{"famille": "bbo", "shard": rel, "sha256": _sha(root, rel)}])
    res = _charger_tier_local(root)
    assert res["bbo"] == 2 and res["bbo_adaptees"] == 2 and res["bbo_denses_non_retenues"] == 1
    premiere, seconde = res["_bbo"]
    assert premiere == {
        "schema_version": "hypersmart.copy_vault_bbo.v1", "coin": "BTC", "received_at_ms": 5_000,
        "exchange_ts_ms": 4_900, "bid_px": 100.0, "bid_sz": 2.0, "ask_px": 100.5, "ask_sz": 3.0,
        "source": "HYPERLIQUID_BBO_WS", "data_origin": "REAL_OBSERVED", "causal_observation": True,
        "provenance_tier": "LOCAL", "adapte_depuis": "bbo_tape"}
    assert (seconde["received_at_ms"], seconde["bid_px"]) == (6_000, 101.0)
    assert all(r.get("quality") != "SAFE" for r in res["_bbo"])          # jamais "prouvable"
