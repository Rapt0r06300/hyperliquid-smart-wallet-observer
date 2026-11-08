"""Tests du lecteur de fills de nœud Hyperliquid local (cœur pur + ingestion)."""
from __future__ import annotations

import json
import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE / "tools"))

import ingester_node_fills as N  # noqa: E402

NOW = 1_800_000_000_000


def _fill(**kw):
    base = {"coin": "ETH", "px": "2000", "sz": "1.5", "side": "B", "time": NOW - 1000,
            "hash": "0xh", "tid": 1, "oid": 7, "dir": "Open Long"}
    base.update(kw)
    return base


def test_extraire_format_events():
    obj = {"block_time": NOW - 900, "block_number": 42,
           "events": [["0xAAA", _fill(tid=1)], ["0xBBB", [_fill(tid=2), _fill(tid=3)]]]}
    got = N.extraire_fills(obj)
    assert len(got) == 3 and got[0][0] == "0xAAA" and got[0][2] == NOW - 900 and got[0][3] == 42


def test_extraire_format_fills():
    obj = {"block_time": NOW, "fills": [dict(_fill(tid=9), user="0xCCC")]}
    got = N.extraire_fills(obj)
    assert len(got) == 1 and got[0][0] == "0xCCC"


def test_parser_fill_node_valide():
    r = N.parser_fill_node("0xABC1234567", _fill(), NOW - 900, 42, now_ms=NOW)
    assert r is not None and r["vault"] == "0xabc1234567" and r["px"] == 2000.0
    assert r["signe"] == 1 and r["source"] == "NODE_FILLS" and r["observed_at_ms"] == NOW - 900
    assert r["isSnapshot"] is False


def test_parser_fill_node_rejets():
    assert N.parser_fill_node("pas0x", _fill(), None, None, now_ms=NOW) is None
    assert N.parser_fill_node("0xABC1234567", _fill(px="0"), None, None, now_ms=NOW) is None
    assert N.parser_fill_node("0xABC1234567", _fill(side="?", dir=""), None, None, now_ms=NOW) is None  # signe indéterminé


def test_ingerer_dedup_et_filtre(tmp_path):
    node = tmp_path / "node" / "node_fills_by_block"
    node.mkdir(parents=True)
    lignes = [
        json.dumps({"block_time": NOW - 900, "block_number": 1,
                    "events": [["0xAAA1111111", _fill(tid=1)], ["0xAAA1111111", _fill(tid=1)]]}),  # doublon
        json.dumps({"block_time": NOW - 800, "block_number": 2,
                    "events": [["0xBBB2222222", _fill(tid=2)]]}),  # autre user
    ]
    (node / "node_fills_by_block.jsonl").write_text("\n".join(lignes), encoding="utf-8")
    out = tmp_path / "runtime" / "data" / "node_fills_tape.jsonl"
    # sans filtre : 2 fills (doublon retiré)
    rap = N.ingerer(node, out, now_ms=NOW)
    assert rap["fills_ecrits"] == 2
    # avec filtre leaders : seul 0xAAA retenu
    rap2 = N.ingerer(node, out, leaders={"0xaaa1111111"}, now_ms=NOW)
    assert rap2["fills_ecrits"] == 1
