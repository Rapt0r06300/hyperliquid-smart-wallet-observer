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



def test_derived_capacity_replay_requires_real_l2_lineage(tmp_path):
    from hl_observer.collection.depth_capacity import capacity_tape_envelope
    from hl_observer.collection.partitioned_tick_dataset import PartitionedTickDatasetWriter
    tick = capacity_tape_envelope(
        venue="bybit", instrument="BTCUSDT",
        bids=[[99, 1]], asks=[[101, 2]],
        exchange_ts_ms=1000, received_ts_ms=1001, receive_mono_ns=100000,
        connection_id="bybit-1", sequence=10, quality="EXPLOITABLE",
        source_raw_l2_payload={"seq": 10, "b": [[99, 1]], "a": [[101, 2]]},
    )
    assert tick is not None
    writer = PartitionedTickDatasetWriter(tmp_path)
    writer.append(tick)
    [asset] = writer.rotate_all()
    result = inspect_asset(asset, {"family": "capacity_tape", "venue": "bybit", "symbol": "BTCUSDT"})
    assert result["record_count"] == 1
    assert result["invalid_record_count"] == 0
    assert result["derived_capacity_lineage_verified"] is True
    assert result["replay_compatible"] is True


def test_derived_capacity_missing_l2_hash_fails_replay(tmp_path):
    from hl_observer.collection.depth_capacity import capacity_tape_envelope
    from hl_observer.collection.partitioned_tick_dataset import PartitionedTickDatasetWriter
    tick = capacity_tape_envelope(
        venue="bitget", instrument="BTCUSDT",
        bids=[[99, 1]], asks=[[101, 2]],
        exchange_ts_ms=1000, received_ts_ms=1001, receive_mono_ns=100000,
        connection_id="bitget-1", sequence=10, quality="EXPLOITABLE",
        source_raw_l2_payload=None,
    )
    assert tick is not None
    writer = PartitionedTickDatasetWriter(tmp_path)
    writer.append(tick)
    [asset] = writer.rotate_all()
    result = inspect_asset(asset, {"family": "capacity_tape", "venue": "bitget", "symbol": "BTCUSDT"})
    assert result["derived_capacity_lineage_verified"] is False
    assert result["replay_compatible"] is False



def _active_ctx_tick(ts, mono):
    import hashlib
    raw = json.dumps({
        "channel": "activeAssetCtx",
        "data": {"coin": "BTC", "ctx": {"markPx": "100"}},
    }, sort_keys=True)
    return {
        "schema_version": "hypersmart.tick.v1",
        "source_id": "hyperliquid_public_ws",
        "channel": "activeAssetCtx",
        "event_kind": "SNAPSHOT",
        "exchange_ts_ms": None,
        "received_ts_ms": ts,
        "local_monotonic_ns": mono,
        "raw_payload": raw,
        "raw_sha256": hashlib.sha256(raw.encode()).hexdigest(),
        "real_execution": False,
        "provenance": {
            "transport": "websocket", "access": "read_only",
            "authenticated": False,
            "timestamp_semantics": "receive_observation_time_only",
        },
    }


def test_context_same_raw_state_at_distinct_observation_times_is_replayable(tmp_path):
    path = tmp_path / "active.jsonl.gz"
    with gzip.open(path, "wt", encoding="utf-8") as handle:
        for ts, mono in [(1000, 100_000), (1001, 101_000)]:
            handle.write(json.dumps(_active_ctx_tick(ts, mono)) + "\n")
    out = inspect_asset(path, {"family": "activeAssetCtx", "source": "hyperliquid_public_ws",
                               "venue": "hyperliquid", "symbol": "BTC"})
    assert out["receive_only_context_verified"] is True
    assert out["replay_compatible"] is True


def test_context_same_monotonic_clock_is_not_deduplicated_by_assumption(tmp_path):
    path = tmp_path / "repeat.jsonl.gz"
    with gzip.open(path, "wt", encoding="utf-8") as handle:
        handle.write(json.dumps(_active_ctx_tick(1000, 10_000)) + "\n")
        handle.write(json.dumps(_active_ctx_tick(1001, 10_000)) + "\n")
    out = inspect_asset(path, {"family": "activeAssetCtx", "source": "hyperliquid_public_ws",
                               "venue": "hyperliquid", "symbol": "BTC"})
    assert out["receive_only_context_verified"] is False
    # A snapshot can be replayable but must not qualify for repair without
    # proof of DISTINCT causal observations.
    assert out["replay_compatible"] is True



def test_historical_vault_http_without_modern_request_type_is_proved_by_raw_payload(tmp_path):
    row = _vault_tick()
    row["provenance"].pop("request_type")
    row["provenance"]["url"] = "https://api.hyperliquid.xyz/info"
    row["parsed_summary"] = {"position_count": 0}
    path = tmp_path / "legacy-vault.jsonl.gz"
    with gzip.open(path, "wt", encoding="utf-8") as output:
        output.write(json.dumps(row) + "\n")
    result = inspect_asset(path, {
        "family": "copy_vault_positions", "source": "hyperliquid_public_info",
        "venue": "hyperliquid",
    })
    assert result["receive_only_snapshot_verified"] is True
    assert result["replay_compatible"] is True


def test_historical_vault_wrong_http_origin_or_position_count_remains_unverified(tmp_path):
    for wrong in ("origin", "position_count", "raw"):
        row = _vault_tick()
        row["provenance"].pop("request_type")
        row["provenance"]["url"] = "https://api.hyperliquid.xyz/info"
        row["parsed_summary"] = {"position_count": 0}
        if wrong == "origin":
            row["provenance"]["url"] = "https://untrusted.example/info"
        elif wrong == "position_count":
            row["parsed_summary"]["position_count"] = 999
        else:
            row["raw_payload"] = json.dumps({"assetPositions": "not a snapshot"})
            import hashlib
            row["raw_sha256"] = hashlib.sha256(row["raw_payload"].encode()).hexdigest()
        path = tmp_path / f"invalid-{wrong}.jsonl.gz"
        with gzip.open(path, "wt", encoding="utf-8") as output:
            output.write(json.dumps(row) + "\n")
        result = inspect_asset(path, {
            "family": "copy_vault_positions", "source": "hyperliquid_public_info",
            "venue": "hyperliquid",
        })
        assert result["receive_only_snapshot_verified"] is False
        assert result["replay_compatible"] is False
