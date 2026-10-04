from __future__ import annotations
from pathlib import Path
import json, tempfile, gzip
from tools.replay_compatibility import inspect_asset

def test_trade_asset_count_and_replay_gate():
    with tempfile.TemporaryDirectory() as d:
        p=Path(d)/"x.jsonl.gz"
        rows=[{"timestamp_ms":1,"trade_id":"a","price":"1","size":"2"},{"timestamp_ms":2,"trade_id":"b","price":"1","size":"3"}]
        with gzip.open(p,"wt",encoding="utf-8") as h:
            for r in rows: h.write(json.dumps(r)+"\n")
        m={"family":"trades","venue":"binance","symbol":"BTC"}
        out=inspect_asset(p,m)
        assert out["record_count"]==2
        assert out["trade_count"]==2
        assert out["replay_compatible"] is True

def test_out_of_order_is_not_replayable():
    with tempfile.TemporaryDirectory() as d:
        p=Path(d)/"x.jsonl"
        p.write_text(json.dumps({"timestamp_ms":2})+"\n"+json.dumps({"timestamp_ms":1})+"\n")
        out=inspect_asset(p,{"family":"trades","venue":"x","symbol":"Y"})
        assert out["out_of_order_count"]==1
        assert out["replay_compatible"] is False

def test_tick_envelope_trade_batch_counts_underlying_trades():
    with tempfile.TemporaryDirectory() as d:
        p=Path(d)/"x.jsonl.gz"
        row={
            "exchange_ts_ms":1,
            "sequence":7,
            "parsed_summary":{"event_count":3},
            "raw_payload":"{}"
        }
        with gzip.open(p,"wt",encoding="utf-8") as h:
            h.write(json.dumps(row)+"\n")
        out=inspect_asset(p,{"family":"trades","venue":"hyperliquid","symbol":"BTC"})
        assert out["record_count"]==1
        assert out["trade_count"]==3
        assert out["replay_compatible"] is True


def test_official_archive_rows_are_replayable_from_exchange_chronology():
    with tempfile.TemporaryDirectory() as d:
        p = Path(d) / "archive.jsonl.gz"
        rows = [
            {"timestamp_ms": 1000, "trade_id": "a", "price": "100", "size": "1", "side": "BUY"},
            {"timestamp_ms": 1001, "trade_id": "b", "price": "101", "size": "2", "side": "SELL"},
        ]
        with gzip.open(p, "wt", encoding="utf-8") as h:
            for row in rows:
                h.write(json.dumps(row) + "\n")
        out = inspect_asset(
            p,
            {
                "family": "trades",
                "venue": "binance",
                "symbol": "BTCUSDT",
                "source": "binance_usdm_official_archive",
            },
        )
        assert out["replay_compatible"] is True
        assert out["replay_reason"] == "STRICT_PARSE_CHRONOLOGY_OK"
