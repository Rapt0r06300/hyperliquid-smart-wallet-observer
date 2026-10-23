from __future__ import annotations

import gzip
import hashlib
import json

from tools.certify_local_l2 import inspect_shard, salvage


def make(kind, native, ts, venue="binance"):
    raw = json.dumps(native, separators=(",", ":"))
    return {
        "venue": venue, "event_kind": kind, "exchange_ts_ms": ts,
        "received_ts_ms": ts + 5, "raw_payload": raw,
        "raw_sha256": hashlib.sha256(raw.encode()).hexdigest(),
    }


def prepare(tmp_path, rows, venue="binance"):
    source = tmp_path / "data.jsonl.gz"
    data = gzip.compress(b"".join(json.dumps(r).encode() + b"\n" for r in rows),
                         mtime=0)
    source.write_bytes(data)
    return source, {
        "dataset_id": "data", "venue": venue, "family": "l2Book",
        "bytes": len(data), "sha256": hashlib.sha256(data).hexdigest(),
    }


def snap(t, seq):
    return make("SNAPSHOT", {"lastUpdateId": seq,
                            "bids": [["99", "2"]], "asks": [["101", "3"]]}, t)


def delta(t, low, seq, prev):
    return make("INCREMENTAL",
                {"U": low, "u": seq, "pu": prev, "b": [["99", "4"]], "a": []}, t)


def test_complete_native_snapshot_and_deltas(tmp_path):
    source, info = prepare(tmp_path, [snap(1, 100), delta(2, 101, 102, 100)])
    result = inspect_shard(source, info)
    assert result["status"] == "CONTINUOUS_L2"
    assert result["segments"] == [{"first_line": 1, "last_line": 2, "records": 2}]


def test_gap_reanchored_without_touching_original(tmp_path):
    rows = [snap(1, 100), delta(2, 101, 102, 100),
            delta(3, 104, 106, 102), snap(4, 200),
            delta(5, 201, 201, 200)]
    source, info = prepare(tmp_path, rows)
    old = source.read_bytes()
    result = inspect_shard(source, info)
    assert result["status"] == "RECOVERABLE_ANCHORED_SPANS"
    assert [(r["first_line"], r["last_line"]) for r in result["segments"]] == [(1, 2), (4, 5)]
    repair = salvage(source, tmp_path / "derived", result)
    with gzip.open(repair["path"], "rt") as handle:
        assert len([json.loads(line) for line in handle]) == 4
    assert salvage(source, tmp_path / "derived", result) == repair
    assert source.read_bytes() == old


def test_missing_anchor_fails_closed(tmp_path):
    source, info = prepare(tmp_path, [delta(2, 101, 102, 100)])
    result = inspect_shard(source, info)
    assert result["status"] == "BLOCKED"
    assert not result["segments"]


def test_tamper_fails_sha256_even_if_gzip_valid(tmp_path):
    source, info = prepare(tmp_path, [snap(1, 100)])
    info["sha256"] = "0" * 64
    result = inspect_shard(source, info)
    assert result["status"] == "BLOCKED"
    assert "COMPRESSED_SHA256_MISMATCH" in result["reasons"]


def test_hyperliquid_snapshot_only_never_claims_continuous(tmp_path):
    def row(t):
        return make("SNAPSHOT", {"channel": "l2Book", "data": {
            "coin": "BTC", "levels": [[{"px": "99", "sz": "2"}],
                                      [{"px": "101", "sz": "3"}]]}}, t, "hyperliquid")
    source, info = prepare(tmp_path, [row(1), row(2)], venue="hyperliquid")
    result = inspect_shard(source, info)
    assert result["status"] == "SNAPSHOT_OBSERVATIONS_ONLY"


def test_bitget_pseq_requires_exact_previous(tmp_path):
    def frame(action, t, seq, pseq=None):
        raw = {"action": action, "data": [
            {"seq": seq, "pseq": pseq,
             "bids": [["99", "2"]], "asks": [["101", "3"]]}]}
        return make("SNAPSHOT" if action == "snapshot" else "UPDATE",
                    raw, t, venue="bitget")
    source, info = prepare(tmp_path,
                           [frame("snapshot", 1, 10), frame("update", 2, 11, 10)],
                           venue="bitget")
    assert inspect_shard(source, info)["status"] == "CONTINUOUS_L2"
    source, info = prepare(tmp_path,
                           [frame("snapshot", 1, 10), frame("update", 2, 12, 9)],
                           venue="bitget")
    assert inspect_shard(source, info)["status"] != "CONTINUOUS_L2"
