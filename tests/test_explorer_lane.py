"""Tests du collecteur feed explorer Hyperliquid (cœur pur, sans réseau)."""
from __future__ import annotations

import json
import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE / "src"))
sys.path.insert(0, str(RACINE / "tools"))

import collecter_explorer_lane as E  # noqa: E402

NOW = 1_800_000_000_000


def test_parser_tx_order():
    tx = {"user": "0xABC123def4567890", "action": {"type": "order",
          "orders": [{"a": 5, "b": True, "p": "100", "s": "2"}]},
          "block": 42, "hash": "0xh1", "time": NOW - 100}
    r = E.parser_tx(tx, now_ms=NOW)
    assert r is not None
    assert r["user"] == "0xabc123def4567890" and r["action_type"] == "order"
    assert r["block"] == 42 and r["hash"] == "0xh1" and "orders" in r
    assert r["source_id"] == E.SOURCE_ID and r["observed_at_ms"] == NOW


def test_parser_tx_user_invalide():
    assert E.parser_tx({"user": "pas0x", "action": {}}, now_ms=NOW) is None
    assert E.parser_tx("pas un dict", now_ms=NOW) is None


def test_est_bloc():
    assert E.est_bloc({"height": 10, "numTxs": 3, "proposer": "x"}) is True
    assert E.est_bloc({"user": "0x", "hash": "h"}) is False


def test_est_action_trading():
    assert E.est_action_trading({"action_type": "order"}) is True
    assert E.est_action_trading({"action_type": "cancel"}) is True
    assert E.est_action_trading({"action_type": "deposit"}) is False


def test_charger_leaders(tmp_path):
    cfg = tmp_path / "config" / "copy_vault_leaders.json"
    cfg.parent.mkdir(parents=True)
    cfg.write_text(json.dumps({"vaults": ["0xAAA1111111", "pas_adresse", "0xbbb2222222"]}),
                   encoding="utf-8")
    s = E._charger_leaders(tmp_path, "config/copy_vault_leaders.json")
    assert s == {"0xaaa1111111", "0xbbb2222222"}
    assert E._charger_leaders(tmp_path, "") is None


def test_collecte_filtre_et_decouverte(tmp_path):
    out = tmp_path / "runtime" / "data" / "explorer_tx_tape.jsonl"
    dec = tmp_path / "runtime" / "data" / "explorer_users_decouverts.json"
    c = E.CollecteExplorer(out, dec, leaders={"0xaaa1111111"}, trading_seulement=True)
    import asyncio
    txs = [
        {"user": "0xAAA1111111", "action": {"type": "order", "orders": []}, "hash": "h1", "block": 1},
        {"user": "0xAAA1111111", "action": {"type": "order", "orders": []}, "hash": "h1", "block": 1},  # doublon hash
        {"user": "0xCCC9999999", "action": {"type": "order"}, "hash": "h2", "block": 1},  # hors filtre -> decouverte
        {"user": "0xAAA1111111", "action": {"type": "deposit"}, "hash": "h3", "block": 1},  # non trading
    ]
    asyncio.run(c.traiter_message(txs, NOW))
    lignes = [json.loads(l) for l in out.read_text(encoding="utf-8").splitlines() if l.strip()]
    assert len(lignes) == 1 and lignes[0]["hash"] == "h1"   # 1 seul (doublon + hors filtre + non trading exclus)
    # le user hors filtre est quand même compté pour la découverte
    assert "0xccc9999999" in c.users_actifs
    c.ecrire_decouverte()
    d = json.loads(dec.read_text(encoding="utf-8"))
    assert d["n_users_vus"] >= 2


def test_fusionner_explorer_dedup(tmp_path):
    import telecharger_explorer_github as T
    (tmp_path / "runtime" / "data").mkdir(parents=True)
    art = tmp_path / "art"
    for j in ("explorer-leaders", "explorer-decouverte"):
        d = art / j
        d.mkdir(parents=True)
        rows = [{"user": "0xa", "hash": "h1", "time": 1}, {"user": "0xa", "hash": "h2", "time": 2}]
        (d / "explorer_tx_tape.jsonl").write_text("\n".join(json.dumps(r) for r in rows), encoding="utf-8")
    rap = T.fusionner_explorer(tmp_path, art)
    assert rap["total_final"] == 2  # h1, h2 (doublons inter-jobs retirés)
