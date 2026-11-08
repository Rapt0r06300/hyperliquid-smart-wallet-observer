"""Tests du collecteur L2 de lane (cœur pur construire_carnet, sans réseau)."""
from __future__ import annotations

import json
import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE / "src"))
sys.path.insert(0, str(RACINE / "tools"))

import collecter_l2_lane as L  # noqa: E402

NOW = 1_800_000_000_000


def _frame(coin="ETH", exch=None, bids=None, asks=None):
    exch = exch if exch is not None else NOW - 100
    bids = bids or [{"px": "2000.0", "sz": "5"}, {"px": "1999.0", "sz": "10"}]
    asks = asks or [{"px": "2001.0", "sz": "4"}, {"px": "2002.0", "sz": "8"}]
    return {"coin": coin, "time": exch, "levels": [bids, asks]}


def test_carnet_valide():
    row, raison = L.construire_carnet(_frame(), recv_ms=NOW)
    assert row is not None and raison == ""
    assert row["coin"] == "ETH" and row["bid"] == 2000.0 and row["ask"] == 2001.0
    assert row["schema_version"] == "hypersmart.copy_vault_l2.v1"


def test_carnet_croise_rejete():
    row, raison = L.construire_carnet(
        _frame(bids=[{"px": "2002", "sz": "1"}], asks=[{"px": "2001", "sz": "1"}]), recv_ms=NOW)
    assert row is None and raison == "marche_croisee"


def test_carnet_niveaux_absents():
    row, raison = L.construire_carnet({"coin": "ETH", "time": NOW - 100, "levels": [[]]}, recv_ms=NOW)
    assert row is None


def test_carnet_lag_trop_grand_rejete():
    # exchange_ts tres ancien -> lag > 30s -> quarantaine
    row, raison = L.construire_carnet(_frame(exch=NOW - 10_000_000), recv_ms=NOW)
    assert row is None and raison in ("lag_causal_depasse", "timestamp_futur")


def test_charger_coins(tmp_path):
    cfg = tmp_path / "config" / "copy_vault_coins.json"
    cfg.parent.mkdir(parents=True)
    cfg.write_text(json.dumps({"coins": ["eth", "BTC", "eth", " sol "]}), encoding="utf-8")
    coins = L._charger_coins(tmp_path, "config/copy_vault_coins.json")
    assert coins == ["ETH", "BTC", "SOL"]  # dédupliqué, normalisé en majuscules


def test_fusionner_carnets_dedup(tmp_path):
    import telecharger_l2_lanes_github as T
    root = tmp_path
    (root / "runtime" / "data").mkdir(parents=True)

    def _carnet(coin, exch):
        return {"schema_version": "hypersmart.copy_vault_l2.v1", "coin": coin,
                "received_at_ms": exch + 50, "exchange_ts_ms": exch,
                "bid": 2000.0, "ask": 2001.0,
                "bids5": [[2000.0, 5.0]], "asks5": [[2001.0, 4.0]],
                "source": "HYPERLIQUID_L2_WS"}

    art = root / "art"
    for sh in (0, 1):
        d = art / f"l2-shard-{sh}"
        d.mkdir(parents=True)
        rows = [_carnet("ETH", NOW - 1000 + sh), _carnet("ETH", NOW - 1000 + sh)]  # doublon interne
        (d / "copy_vault_l2_lane.jsonl").write_text("\n".join(json.dumps(r) for r in rows), encoding="utf-8")

    rap = T.fusionner_carnets(root, art, now_ms=NOW)
    # 2 instants distincts (NOW-1000 et NOW-999), doublons retirés
    assert rap["total_final"] == 2
    cible = root / "runtime" / "data" / "copy_vault_l2_tape.jsonl"
    assert cible.exists() and len(cible.read_text().splitlines()) == 2
