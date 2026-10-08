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


def test_bybit_tick_envelope_reads_trade_identity_from_raw_payload():
    with tempfile.TemporaryDirectory() as d:
        p=Path(d)/"bybit.jsonl.gz"
        rows=[
            {
                "exchange_ts_ms":1000,
                "sequence":None,
                "raw_payload":{
                    "timestamp":"1.000",
                    "symbol":"BTCUSDT",
                    "side":"Buy",
                    "size":"0.1",
                    "price":"100",
                    "trdMatchID":"match-a",
                },
            },
            {
                "exchange_ts_ms":1001,
                "sequence":None,
                "raw_payload":{
                    "timestamp":"1.001",
                    "symbol":"BTCUSDT",
                    "side":"Sell",
                    "size":"0.2",
                    "price":"101",
                    "trdMatchID":"match-b",
                },
            },
        ]
        with gzip.open(p,"wt",encoding="utf-8") as h:
            for row in rows:
                h.write(json.dumps(row)+"\n")
        out=inspect_asset(p,{"family":"trades","venue":"bybit","symbol":"BTCUSDT"})
        assert out["trade_count"]==2
        assert out["invalid_record_count"]==0
        assert out["duplicate_count"]==0
        assert out["replay_compatible"] is True


def test_non_trade_replay_does_not_require_a_trade_identity():
    with tempfile.TemporaryDirectory() as d:
        p=Path(d)/"bbo.jsonl.gz"
        rows=[
            {"exchange_ts_ms":1000,"raw_payload":{"bid":"100","ask":"101"}},
            {"exchange_ts_ms":1001,"raw_payload":{"bid":"100.5","ask":"101.5"}},
        ]
        with gzip.open(p,"wt",encoding="utf-8") as h:
            for row in rows:
                h.write(json.dumps(row)+"\n")
        out=inspect_asset(p,{"family":"bbo","venue":"hyperliquid","symbol":"BTC"})
        assert out["invalid_record_count"]==0
        assert out["replay_compatible"] is True



def _vault_tick(*, good=True, family="copy_vault_positions", ts=1000):
    import hashlib
    source = {
        "copy_vault_positions": "hyperliquid_public_info",
        "copy_vault_selection": "hyperliquid_public_vaults",
    }[family]
    raw = json.dumps({"assetPositions": []}) if family == "copy_vault_positions" else json.dumps({"selection": {}})
    provenance = {
        "transport": "https", "access": "read_only", "authenticated": False,
    }
    if family == "copy_vault_positions":
        provenance["request_type"] = "clearinghouseState"
    else:
        provenance["selection_causal"] = True
    return {
        "source_id": source, "channel": family, "event_kind": "SNAPSHOT",
        "received_ts_ms": ts, "exchange_ts_ms": None, "local_monotonic_ns": ts * 1000,
        "real_execution": False, "raw_payload": raw,
        "raw_sha256": hashlib.sha256(raw.encode()).hexdigest() if good else "bad",
        "provenance": provenance,
    }


def test_receive_only_copy_vault_snapshots_are_replayable_with_strict_proof(tmp_path):
    for family in ("copy_vault_positions", "copy_vault_selection"):
        path = tmp_path / (family + ".jsonl.gz")
        with gzip.open(path, "wt", encoding="utf-8") as handle:
            for ts in (1000, 1001):
                handle.write(json.dumps(_vault_tick(family=family, ts=ts)) + "\n")
        result = inspect_asset(path, {
            "family": family, "source": _vault_tick(family=family)["source_id"],
            "venue": "hyperliquid",
        })
        assert result["record_count"] == 2
        assert result["replay_compatible"] is True
        assert result["receive_only_snapshot_verified"] is True


def test_bad_hash_or_fabricated_exchange_time_never_salvages_vault_snapshot(tmp_path):
    for mode in ("bad_hash", "exchange_ts", "wrong_transport"):
        row = _vault_tick()
        if mode == "bad_hash":
            row["raw_sha256"] = "0" * 64
        elif mode == "exchange_ts":
            row["exchange_ts_ms"] = 1234
        else:
            row["provenance"]["transport"] = "websocket"
        path = tmp_path / (mode + ".jsonl.gz")
        with gzip.open(path, "wt", encoding="utf-8") as handle:
            handle.write(json.dumps(row) + "\n")
        result = inspect_asset(path, {
            "family": "copy_vault_positions", "source": "hyperliquid_public_info",
            "venue": "hyperliquid",
        })
        assert result["replay_compatible"] is False
        assert result["receive_only_snapshot_verified"] is False


def test_receive_only_vault_snapshot_out_of_order_fails_closed(tmp_path):
    path = tmp_path / "outoforder.jsonl.gz"
    with gzip.open(path, "wt", encoding="utf-8") as handle:
        handle.write(json.dumps(_vault_tick(ts=1001)) + "\n")
        handle.write(json.dumps(_vault_tick(ts=1000)) + "\n")
    result = inspect_asset(path, {
        "family": "copy_vault_positions", "source": "hyperliquid_public_info",
        "venue": "hyperliquid",
    })
    assert result["out_of_order_count"] == 1
    assert result["replay_compatible"] is False
