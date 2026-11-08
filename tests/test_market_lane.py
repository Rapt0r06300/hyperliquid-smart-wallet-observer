"""Tests du collecteur marché (trades + candle), cœur pur sans réseau."""
from __future__ import annotations

import json
import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE / "src"))
sys.path.insert(0, str(RACINE / "tools"))

import collecter_market_lane as M  # noqa: E402

NOW = 1_800_000_000_000


def test_parser_trade_valide():
    r = M.parser_trade({"coin": "ETH", "side": "B", "px": "2000.5", "sz": "1.5",
                        "time": NOW - 50, "hash": "0xh", "tid": 42}, recv_ms=NOW)
    assert r is not None and r["price"] == 2000.5 and r["size"] == 1.5
    assert r["aggressor_side"] == "BUY" and r["exchange_ts_ms"] == NOW - 50
    assert r["schema_version"] == "hypersmart.copy_vault_trades.v1"


def test_parser_trade_rejets():
    assert M.parser_trade({"coin": "ETH", "px": "0", "sz": "1", "time": NOW}, recv_ms=NOW) is None
    assert M.parser_trade({"coin": "ETH", "px": "1", "sz": "1", "time": NOW + 10}, recv_ms=NOW) is None  # futur
    assert M.parser_trade("pas dict", recv_ms=NOW) is None


def test_parser_candle_valide():
    r = M.parser_candle({"s": "ETH", "i": "1m", "t": NOW - 60000, "T": NOW, "o": "2000",
                         "h": "2010", "l": "1995", "c": "2005", "v": "100", "n": 50}, recv_ms=NOW)
    assert r is not None and r["open"] == 2000.0 and r["close"] == 2005.0
    assert r["volume"] == 100.0 and r["schema_version"] == "hypersmart.copy_vault_candle.v1"


def test_charger_coins(tmp_path):
    cfg = tmp_path / "config" / "copy_vault_coins.json"
    cfg.parent.mkdir(parents=True)
    cfg.write_text(json.dumps({"coins": ["eth", "BTC", "eth"]}), encoding="utf-8")
    assert M._charger_coins(tmp_path, "config/copy_vault_coins.json") == ["ETH", "BTC"]


def test_dedup_trades(tmp_path):
    import asyncio
    lane = M.LaneMarche(tmp_path / "t.jsonl", tmp_path / "c.jsonl", intervalle="1m")
    row = M.parser_trade({"coin": "ETH", "side": "B", "px": "1", "sz": "1", "time": NOW - 1,
                          "hash": "0xh", "tid": 7}, recv_ms=NOW)

    async def go():
        await lane.ecrire_trade(row)
        await lane.ecrire_trade(dict(row))  # doublon
    asyncio.run(go())
    assert lane.trades == 1
