"""Tests du collecteur de contexte leader (positions + TWAP), cœur pur sans réseau."""
from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE / "src"))
sys.path.insert(0, str(RACINE / "tools"))

import collecter_contexte_lane as C  # noqa: E402

NOW = 1_800_000_000_000


def test_parser_positions_filtre_plates():
    data = {"user": "0xABC", "assetPositions": [
        {"position": {"coin": "ETH", "szi": "2.5", "entryPx": "2000", "unrealizedPnl": "120"}},
        {"position": {"coin": "BTC", "szi": "0"}},            # plate -> exclue
        {"position": {"coin": "SOL"}},                         # szi absent -> exclue
    ]}
    r = C.parser_positions(data, user="0xABC", recv_ms=NOW)
    assert [x["coin"] for x in r] == ["ETH"]
    assert r[0]["szi"] == 2.5 and r[0]["vault"] == "0xabc" and r[0]["source"] == "CLEARINGHOUSE_WS"


def test_parser_twap_fills():
    data = {"user": "0xABC", "fills": [
        {"coin": "ETH", "px": "2001", "sz": "0.3", "time": NOW - 5, "side": "B", "tid": 11},
        {"coin": "ETH", "px": "0", "sz": "1", "time": NOW, "side": "A"},   # px<=0 -> rejet
    ]}
    r = C.parser_twap_fills(data, user="0xABC", recv_ms=NOW)
    assert len(r) == 1 and r[0]["signe"] == 1 and r[0]["source"] == "LIVE_TWAP"
    assert r[0]["observed_at_ms"] == NOW and r[0]["is_snapshot"] is False


def test_parser_twap_fills_enveloppe():
    data = {"twapSliceFills": [{"fill": {"coin": "BTC", "px": "50000", "sz": "0.01",
                                         "time": NOW - 10, "side": "A", "tid": 1}}]}
    r = C.parser_twap_fills(data, user="0xZZZ", recv_ms=NOW)
    assert len(r) == 1 and r[0]["coin"] == "BTC" and r[0]["signe"] == -1


def test_dedup_twap(tmp_path):
    lane = C.LaneContexte(tmp_path / "p.jsonl", tmp_path / "t.jsonl")
    rows = C.parser_twap_fills({"user": "0xA", "fills": [
        {"coin": "ETH", "px": "1", "sz": "1", "time": NOW - 1, "side": "B", "tid": 5}]},
        user="0xA", recv_ms=NOW)

    async def go():
        await lane.ecrire_twap(rows)
        await lane.ecrire_twap(list(rows))  # doublon
        await lane.ecrire_positions(C.parser_positions(
            {"user": "0xA", "assetPositions": [{"position": {"coin": "ETH", "szi": "1"}}]},
            user="0xA", recv_ms=NOW))
    asyncio.run(go())
    assert lane.twap == 1 and lane.positions == 1


def test_charger_leaders(tmp_path):
    cfg = tmp_path / "config" / "copy_vault_leaders.json"
    cfg.parent.mkdir(parents=True)
    cfg.write_text(json.dumps({"vaults": ["0xAAA1111111", "court", "0xBBB2222222"]}), encoding="utf-8")
    s = C._charger_leaders(tmp_path, "config/copy_vault_leaders.json")
    assert s == ["0xAAA1111111", "0xBBB2222222"]
