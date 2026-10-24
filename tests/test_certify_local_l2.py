from __future__ import annotations

import gzip
import hashlib
import json
import os
import sqlite3

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


def test_full_offline_report_and_fast_receipt_resume(tmp_path):
    from tools.certify_local_l2 import run
    from pathlib import Path

    root = tmp_path / "repository"
    destination = root / "runtime" / "recovery" / "full"
    stored = destination / "usable" / "shards" / "sample-release"
    stored.mkdir(parents=True)
    path, row = prepare(tmp_path, [snap(1, 100), delta(2, 101, 102, 100)])
    shard_path = stored / "data.jsonl.gz"
    shard_path.write_bytes(path.read_bytes())
    row.update({"quality_status": "SAFE", "replay_compatible": True,
                "asset_verified": True, "validation_allowed": True,
                "release_tag": "sample-release", "symbol": "BTCUSDT"})
    (root / "catalog").mkdir()
    (root / "catalog" / "DATA_INDEX.json").write_text(
        json.dumps({"schema": "alina.data_index.v2", "shards": [row]}),
        encoding="utf-8",
    )
    first = run(root, destination, workers=2)
    assert first["totals"] == {"CONTINUOUS_L2": 1}
    assert first["cache_reused_without_new_hash"] == 0
    second = run(root, destination, workers=2, resume=True)
    assert second["cache_reused_without_new_hash"] == 1
    assert second["totals"] == first["totals"]
    assert shard_path.read_bytes() == path.read_bytes()


def test_cross_shard_snapshot_then_incremental_proof(tmp_path):
    # A delta-only shard is not lost when a prior immutable, SHA-checked
    # shard supplies the authentic native snapshot and matching sequence.
    anchor, first = prepare(tmp_path, [snap(1, 100)])
    carried = {}
    initial = inspect_shard(anchor, first, carry=carried)
    assert initial["status"] == "SNAPSHOT_OBSERVATIONS_ONLY"
    assert carried["seq"] == 100
    continuation, second = prepare(tmp_path, [delta(2, 101, 102, 100)])
    second["dataset_id"] = "continuation"
    linked = inspect_shard(continuation, second, carry=carried)
    assert linked["status"] == "CONTINUOUS_L2_CROSS_SHARD"
    assert linked["previous_sha_verified_shard"] == "data"
    assert inspect_shard(continuation, second)["status"] == "BLOCKED"


def test_bad_digest_poisoned_link_is_not_carried_forward(tmp_path):
    anchor, first = prepare(tmp_path, [snap(1, 100)])
    first["sha256"] = "0" * 64
    carried = {}
    result = inspect_shard(anchor, first, carry=carried)
    assert result["status"] == "BLOCKED"
    assert not carried


def test_missing_catalog_shards_are_counted_not_mislabeled_corrupt(tmp_path):
    from tools.certify_local_l2 import run

    root = tmp_path / "repo"
    dest = root / "runtime" / "recovery" / "full"
    have = dest / "usable" / "shards" / "release"
    have.mkdir(parents=True)
    src, row = prepare(tmp_path, [snap(1, 100)])
    (have / "data.jsonl.gz").write_bytes(src.read_bytes())
    row.update({"quality_status": "SAFE", "replay_compatible": True,
                "release_tag": "release", "symbol": "BTCUSDT"})
    missing = {**row, "dataset_id": "not_yet_downloaded"}
    (root / "catalog").mkdir()
    (root / "catalog" / "DATA_INDEX.json").write_text(
        json.dumps({"schema": "alina.data_index.v2", "shards": [row, missing]}),
        encoding="utf-8",
    )
    report = run(root, dest)
    assert report["indexed_safe_l2_shards"] == 2
    assert report["not_downloaded_locally"] == 1
    assert report["totals"] == {"SNAPSHOT_OBSERVATIONS_ONLY": 1}


def test_report_is_compact_and_database_separates_snapshot_from_continuous(tmp_path):
    from tools.certify_local_l2 import run

    root = tmp_path / "repo"
    dest = root / "runtime" / "recovery" / "full"
    stored = dest / "usable" / "shards" / "release"
    stored.mkdir(parents=True)
    continuous_path, continuous = prepare(
        tmp_path, [snap(1, 100), delta(2, 101, 102, 100)]
    )
    continuous_bytes = continuous_path.read_bytes()
    snapshot_path, snapshot = prepare(tmp_path, [snap(3, 200)])
    (stored / "continuous.jsonl.gz").write_bytes(continuous_bytes)
    (stored / "snapshot.jsonl.gz").write_bytes(snapshot_path.read_bytes())
    continuous.update({
        "dataset_id": "continuous", "quality_status": "SAFE",
        "replay_compatible": True, "release_tag": "release",
        "symbol": "BTCUSDT",
    })
    snapshot.update({
        "dataset_id": "snapshot", "quality_status": "SAFE",
        "replay_compatible": True, "release_tag": "release",
        "symbol": "ETHUSDT",
    })
    (root / "catalog").mkdir()
    (root / "catalog" / "DATA_INDEX.json").write_text(
        json.dumps({"schema": "alina.data_index.v2", "shards": [continuous, snapshot]}),
        encoding="utf-8",
    )

    report = run(root, dest, workers=2)

    assert "l2_rows" not in report
    assert report["admission"] == {
        "snapshot_backtestable_shards": 2,
        "continuous_replayable_shards": 1,
        "reanchored_segment_assets": 0,
        "blocked_shards": 0,
    }
    details = dest / report["details"]["path"]
    assert details.name == "LOCAL_L2_CERTIFICATION_ROWS.jsonl.gz"
    assert details.stat().st_size == report["details"]["bytes"]
    assert hashlib.sha256(details.read_bytes()).hexdigest() == report["details"]["sha256"]
    with gzip.open(details, "rt", encoding="utf-8") as stream:
        rows = [json.loads(line) for line in stream]
    assert {row["dataset_id"] for row in rows} == {"continuous", "snapshot"}

    with sqlite3.connect(dest / "SAFE_SHARDS.sqlite3") as connection:
        snapshot_ids = {
            row[0] for row in connection.execute(
                "SELECT dataset_id FROM current_l2_snapshot_backtestable"
            )
        }
        replay_ids = {
            row[0] for row in connection.execute(
                "SELECT dataset_id FROM current_l2_continuous_replayable"
            )
        }
    assert snapshot_ids == {"continuous", "snapshot"}
    assert replay_ids == {"continuous"}


def test_l2_database_begin_hides_previous_complete_admission(tmp_path):
    from tools.certify_local_l2 import _L2AdmissionRegistry

    registry = _L2AdmissionRegistry(tmp_path)
    registry.begin("a" * 64)
    registry.finalize(
        "a" * 64,
        [{
            "dataset_id": "old", "release_tag": "r", "source_sha256": "b" * 64,
            "source": "old.gz", "status": "CONTINUOUS_L2", "records": 1,
            "valid_records": 1, "reasons": {}, "segments": [],
        }],
        details_sha256="c" * 64,
    )
    assert registry.count_view("current_l2_continuous_replayable") == 1
    registry.begin("d" * 64)
    assert registry.count_view("current_l2_continuous_replayable") == 0
    registry.close()


def _cross_shard_fixture(tmp_path):
    root = tmp_path / "repo"
    dest = root / "runtime" / "recovery" / "full"
    stored = dest / "usable" / "shards" / "release"
    stored.mkdir(parents=True)
    anchor_path, anchor = prepare(tmp_path, [snap(1, 100)])
    anchor_bytes = anchor_path.read_bytes()
    continuation_path, continuation = prepare(
        tmp_path, [delta(2, 101, 102, 100)]
    )
    (stored / "anchor.jsonl.gz").write_bytes(anchor_bytes)
    (stored / "continuation.jsonl.gz").write_bytes(continuation_path.read_bytes())
    common = {
        "quality_status": "SAFE", "replay_compatible": True,
        "release_tag": "release", "symbol": "BTCUSDT",
    }
    anchor.update(common, dataset_id="anchor", start_ts_ms=1)
    continuation.update(common, dataset_id="continuation", start_ts_ms=2)
    (root / "catalog").mkdir()
    (root / "catalog" / "DATA_INDEX.json").write_text(
        json.dumps({"schema": "alina.data_index.v2",
                    "shards": [anchor, continuation]}), encoding="utf-8"
    )
    return root, dest, stored


def test_cross_shard_resume_reuses_unchanged_complete_group(tmp_path, monkeypatch):
    import tools.certify_local_l2 as module

    root, dest, _ = _cross_shard_fixture(tmp_path)
    first = module.run(root, dest, cross_shard=True)
    assert first["totals"] == {
        "SNAPSHOT_OBSERVATIONS_ONLY": 1,
        "CONTINUOUS_L2_CROSS_SHARD": 1,
    }

    def unexpected_scan(*_args, **_kwargs):
        raise AssertionError("unchanged group was rescanned")

    monkeypatch.setattr(module, "inspect_shard", unexpected_scan)
    second = module.run(root, dest, cross_shard=True, resume=True)
    assert second["cache_reused_without_new_hash"] == 2
    assert second["totals"] == first["totals"]


def test_cross_shard_resume_invalidates_whole_group_when_member_stat_changes(
    tmp_path, monkeypatch
):
    import tools.certify_local_l2 as module

    root, dest, stored = _cross_shard_fixture(tmp_path)
    module.run(root, dest, cross_shard=True)
    target = stored / "continuation.jsonl.gz"
    stat = target.stat()
    os.utime(target, ns=(stat.st_atime_ns, stat.st_mtime_ns + 1_000_000))
    original = module.inspect_shard
    calls = []

    def counted(*args, **kwargs):
        calls.append(args[0])
        return original(*args, **kwargs)

    monkeypatch.setattr(module, "inspect_shard", counted)
    module.run(root, dest, cross_shard=True, resume=True)
    assert len(calls) == 2


def test_gate_recorded_rest_anchor_can_prove_following_native_delta(tmp_path):
    raw = {
        "id": 100, "current": 1,
        "bids": [["99", "2"]], "asks": [["101", "3"]],
    }
    anchor = make("SNAPSHOT", raw, 1, venue="gate")
    anchor.update({
        "source_id": "gate_public_rest", "channel": "l2Book",
        "provenance": {"snapshot_role": "official_base_for_incremental_depth"},
    })
    update = make("UPDATE", {
        "channel": "futures.order_book_update", "event": "update",
        "result": {"U": 101, "u": 102, "t": 2,
                   "b": [["99", "4"]], "a": []},
    }, 2, venue="gate")
    update["channel"] = "l2Book"
    source, info = prepare(tmp_path, [anchor, update], venue="gate")
    assert inspect_shard(source, info)["status"] == "CONTINUOUS_L2"


def test_new_empty_local_selection_hides_previous_l2_admission(tmp_path):
    import pytest
    from tools.certify_local_l2 import run

    root, dest, _ = _cross_shard_fixture(tmp_path)
    run(root, dest, cross_shard=True)
    (root / "catalog" / "DATA_INDEX.json").write_text(
        json.dumps({"schema": "alina.data_index.v2", "shards": []}),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="NO_LOCALLY_DOWNLOADED_SAFE_L2_SHARDS_FOUND"):
        run(root, dest)

    with sqlite3.connect(dest / "SAFE_SHARDS.sqlite3") as connection:
        assert connection.execute(
            "SELECT COUNT(*) FROM current_l2_snapshot_backtestable"
        ).fetchone()[0] == 0


def test_repaired_segments_are_registered_separately_from_native_continuity(tmp_path):
    from tools.certify_local_l2 import run

    root = tmp_path / "repo"
    dest = root / "runtime" / "recovery" / "full"
    stored = dest / "usable" / "shards" / "release"
    stored.mkdir(parents=True)
    rows = [snap(1, 100), delta(2, 101, 102, 100),
            delta(3, 104, 106, 102), snap(4, 200),
            delta(5, 201, 201, 200)]
    source, row = prepare(tmp_path, rows)
    (stored / "recoverable.jsonl.gz").write_bytes(source.read_bytes())
    row.update({
        "dataset_id": "recoverable", "quality_status": "SAFE",
        "replay_compatible": True, "release_tag": "release",
        "symbol": "BTCUSDT",
    })
    (root / "catalog").mkdir()
    (root / "catalog" / "DATA_INDEX.json").write_text(
        json.dumps({"schema": "alina.data_index.v2", "shards": [row]}),
        encoding="utf-8",
    )

    report = run(root, dest, repair=True)

    assert report["admission"]["reanchored_segment_assets"] == 1
    assert report["admission"]["continuous_replayable_shards"] == 0
    with sqlite3.connect(dest / "SAFE_SHARDS.sqlite3") as connection:
        repaired = connection.execute(
            "SELECT source_dataset_id, output_sha256 "
            "FROM current_l2_reanchored_segment_assets"
        ).fetchall()
    with gzip.open(dest / report["details"]["path"], "rt", encoding="utf-8") as stream:
        detail = json.loads(next(stream))
    assert repaired == [("recoverable", detail["repair"]["sha256"])]
