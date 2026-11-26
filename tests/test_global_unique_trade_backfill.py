from __future__ import annotations

import gzip
import json
import sys
import time
from pathlib import Path

import pytest

from tools import backfill_global_unique_trade_counts as global_counts
from tools.global_unique_trade_patch import (
    SCHEMA_V5,
    compact_global_unique_count_rows,
    global_unique_count_rows,
)
from tools.partitioned_data_index import partition_index, read_index, save_index


def test_global_unique_patch_reader_skips_large_sibling_values(tmp_path, monkeypatch):
    patch = tmp_path / "patch.json"
    patch.write_bytes(
        b'{"counts":{"failure_attempts":{"nested":9},"padding":"'
        + (b"x" * 2_000_000)
        + b'"},"failure_attempts":{"wallet-a":2}}'
    )
    decoded_lengths = []
    original_loads = global_counts.json.loads

    def track_decoded_value(value, *args, **kwargs):
        decoded_lengths.append(len(value))
        return original_loads(value, *args, **kwargs)

    monkeypatch.setattr(global_counts.json, "loads", track_decoded_value)

    assert global_counts._read_top_level_json_field(patch, "failure_attempts") == {
        "wallet-a": 2,
    }
    assert decoded_lengths
    assert max(decoded_lengths) < 128


def test_global_unique_patch_reader_ignores_nested_field_and_handles_missing(tmp_path):
    patch = tmp_path / "patch.json"
    patch.write_text('{"counts":{"failure_attempts":{"nested":3}}}', encoding="utf-8")
    assert global_counts._read_top_level_json_field(patch, "failure_attempts") is None


@pytest.mark.parametrize(
    "document",
    [
        '{"counts":{},,"failure_attempts":{}}',
        '{"failure_attempts":{invalid}}',
        '{"failure_attempts":{},"failure_attempts":{}}',
    ],
)
def test_global_unique_patch_reader_rejects_malformed_or_ambiguous_receipts(
    tmp_path,
    document,
):
    patch = tmp_path / "patch.json"
    patch.write_text(document, encoding="utf-8")
    with pytest.raises(ValueError):
        global_counts._read_top_level_json_field(patch, "failure_attempts")


def test_global_unique_patch_is_atomically_replaced_and_preserves_last_good_on_failure(
    tmp_path, monkeypatch,
):
    patch = tmp_path / "TRADE_UNIQUE_COUNT_PATCH.json"
    previous = b'{"previous":true}\n'
    patch.write_bytes(previous)

    global_counts._write_global_unique_patch(patch, {"coverage_complete": False, "rows": 3})
    assert json.loads(patch.read_text(encoding="utf-8")) == {
        "coverage_complete": False,
        "rows": 3,
    }
    assert not list(tmp_path.glob(".TRADE_UNIQUE_COUNT_PATCH.json.*.tmp"))

    patch.write_bytes(previous)

    def fail_replace(_source, _destination):
        raise PermissionError("simulated atomic replace failure")

    monkeypatch.setattr(global_counts.os, "replace", fail_replace)
    with pytest.raises(PermissionError, match="simulated atomic replace failure"):
        global_counts._write_global_unique_patch(patch, {"new": "receipt"})

    assert patch.read_bytes() == previous
    assert not list(tmp_path.glob(".TRADE_UNIQUE_COUNT_PATCH.json.*.tmp"))

    monkeypatch.setattr(global_counts, "GLOBAL_UNIQUE_PATCH_MAX_BYTES", 1)
    with pytest.raises(ValueError, match="GLOBAL_UNIQUE_PATCH_NEEDS_PARTITION"):
        global_counts._write_global_unique_patch(patch, {"oversized": True})
    assert patch.read_bytes() == previous
    assert not list(tmp_path.glob(".TRADE_UNIQUE_COUNT_PATCH.json.*.tmp"))


def test_checkpoint_resumes_without_recounting_and_rejects_changed_shard(tmp_path):
    rows = [
        {"dataset_id": "a", "sha256": "a" * 64, "trade_count": 2, "trade_count_exact": True},
        {"dataset_id": "b", "sha256": "b" * 64, "trade_count": 2, "trade_count_exact": True},
    ]
    checkpoint = tmp_path / "identities.sqlite"
    database = global_counts._open_checkpoint(checkpoint, rows)
    identities = tmp_path / "ids.txt"
    identities.write_text("trade-a\ntrade-b\n", encoding="utf-8")
    global_counts._merge_checkpoint_shard(database, rows[0], {
        "exact": True, "trade_count_scanned": 2,
        "unique_trade_count": 2, "identity_path": str(identities),
    })
    database.close()

    resumed = global_counts._open_checkpoint(checkpoint, rows)
    identities.write_text("trade-b\ntrade-c\n", encoding="utf-8")
    global_counts._merge_checkpoint_shard(resumed, rows[1], {
        "exact": True, "trade_count_scanned": 2,
        "unique_trade_count": 2, "identity_path": str(identities),
    })
    assert resumed.execute("SELECT COUNT(*) FROM ids").fetchone()[0] == 3
    assert resumed.execute("SELECT SUM(global_new) FROM completed").fetchone()[0] == 3
    resumed.close()

    with pytest.raises(ValueError, match="provenance"):
        global_counts._open_checkpoint(checkpoint, [{**rows[0], "sha256": "c" * 64}, rows[1]])


def test_global_unique_patch_v5_compact_rows_round_trip_and_fail_closed():
    identity_version = global_counts.IDENTITY_VERSION
    source = {
        "dataset-a": {
            "asset_sha256": "a" * 64,
            "trade_count_scanned": 4,
            "unique_trade_count": 3,
            "global_new_identity_count": 2,
            "cross_shard_overlap_count": 1,
            "unique_trade_count_exact": True,
            "identity_version": identity_version,
        }
    }
    compact = compact_global_unique_count_rows(
        source,
        identity_version=identity_version,
    )
    document = {
        "schema": SCHEMA_V5,
        "identity_version": identity_version,
        "counts": compact,
    }

    assert compact["dataset-a"] == ["a" * 64, 4, 3, 2, 1, True]
    assert global_unique_count_rows(document)["dataset-a"] == {
        "asset_sha256": "a" * 64,
        "trade_count_scanned": 4,
        "unique_trade_count": 3,
        "global_new_identity_count": 2,
        "cross_shard_overlap_count": 1,
        "unique_trade_count_exact": True,
        "identity_version": identity_version,
    }
    assert global_unique_count_rows({**document, "counts": {
        "dataset-a": ["a" * 64, 4, 4, 2, 1, True],
    }}).get("dataset-a") is None
    assert global_unique_count_rows({**document, "schema": "unknown"}) == {}


def test_checkpoint_validates_unsorted_inventory_without_duplicate_ids(tmp_path):
    rows = [
        {"dataset_id": "b", "sha256": "b" * 64, "trade_count": 1, "trade_count_exact": True},
        {"dataset_id": "a", "sha256": "a" * 64, "trade_count": 1, "trade_count_exact": True},
    ]
    database = global_counts._open_checkpoint(tmp_path / "identities.sqlite", rows)
    assert [row["dataset_id"] for row in rows] == ["a", "b"]
    database.close()

    duplicates = [rows[0], {**rows[0]}]
    with pytest.raises(ValueError, match="duplicate or empty candidate"):
        global_counts._open_checkpoint(tmp_path / "duplicate.sqlite", duplicates)


def test_identity_merge_batches_preserve_cross_shard_overlap_and_exact_counts(tmp_path):
    rows = [
        {"dataset_id": "a", "sha256": "a" * 64, "trade_count": 3000,
         "trade_count_exact": True},
        {"dataset_id": "b", "sha256": "b" * 64, "trade_count": 5000,
         "trade_count_exact": True},
    ]
    database = global_counts._open_checkpoint(tmp_path / "identities.sqlite", rows)
    first = tmp_path / "first.txt"
    first.write_text(
        "".join(f"trade-{number:05d}\n" for number in range(3000)),
        encoding="utf-8",
    )
    second = tmp_path / "second.txt"
    second.write_text(
        "".join(f"trade-{number:05d}\n" for number in range(5000)),
        encoding="utf-8",
    )

    global_counts._merge_checkpoint_shard(database, rows[0], {
        "exact": True, "trade_count_scanned": 3000,
        "unique_trade_count": 3000, "identity_path": str(first),
    })
    global_counts._merge_checkpoint_shard(database, rows[1], {
        "exact": True, "trade_count_scanned": 5000,
        "unique_trade_count": 5000, "identity_path": str(second),
    })

    assert database.execute("SELECT COUNT(*) FROM ids").fetchone()[0] == 5000
    assert database.execute(
        "SELECT global_new FROM completed WHERE dataset_id='a'"
    ).fetchone()[0] == 3000
    assert database.execute(
        "SELECT global_new FROM completed WHERE dataset_id='b'"
    ).fetchone()[0] == 2000
    assert database.execute(
        "SELECT SUM(global_new) FROM completed"
    ).fetchone()[0] == 5000
    database.close()


def test_checkpoint_rolls_back_incomplete_identity_file(tmp_path):
    row = {"dataset_id": "a", "sha256": "a" * 64, "trade_count": 2, "trade_count_exact": True}
    database = global_counts._open_checkpoint(tmp_path / "identities.sqlite", [row])
    identities = tmp_path / "ids.txt"
    identities.write_text("only-one\n", encoding="utf-8")
    with pytest.raises(ValueError, match="unique identity count"):
        global_counts._merge_checkpoint_shard(database, row, {
            "exact": True, "trade_count_scanned": 2,
            "unique_trade_count": 2, "identity_path": str(identities),
        })
    assert database.execute("SELECT COUNT(*) FROM ids").fetchone()[0] == 0
    assert database.execute("SELECT COUNT(*) FROM completed").fetchone()[0] == 0
    database.close()


def test_checkpoint_batch_savepoint_rolls_back_only_failed_shard(tmp_path):
    rows = [
        {"dataset_id": "a", "sha256": "a" * 64, "trade_count": 2, "trade_count_exact": True},
        {"dataset_id": "b", "sha256": "b" * 64, "trade_count": 2, "trade_count_exact": True},
    ]
    database = global_counts._open_checkpoint(tmp_path / "identities.sqlite", rows)
    good = tmp_path / "good.txt"
    good.write_text("trade-a\ntrade-b\n", encoding="utf-8")
    bad = tmp_path / "bad.txt"
    bad.write_text("trade-c\n", encoding="utf-8")

    database.execute("BEGIN IMMEDIATE")
    global_counts._merge_checkpoint_shard(
        database,
        rows[0],
        {
            "exact": True,
            "trade_count_scanned": 2,
            "unique_trade_count": 2,
            "identity_path": str(good),
        },
        manage_transaction=False,
    )
    with pytest.raises(ValueError, match="unique identity count"):
        global_counts._merge_checkpoint_shard(
            database,
            rows[1],
            {
                "exact": True,
                "trade_count_scanned": 2,
                "unique_trade_count": 2,
                "identity_path": str(bad),
            },
            manage_transaction=False,
        )
    database.commit()

    assert database.execute("SELECT COUNT(*) FROM completed").fetchone()[0] == 1
    assert database.execute("SELECT COUNT(*) FROM ids").fetchone()[0] == 2
    database.close()


def test_scan_rejects_dataset_id_outside_temporary_root(tmp_path, monkeypatch):
    monkeypatch.setattr(global_counts, "_download", lambda *_a: pytest.fail("download must not start"))
    with pytest.raises(ValueError, match="escapes temporary scan root"):
        global_counts._scan_candidate({"dataset_id": "../outside"}, tmp_path / "scan")


def test_bounded_scan_resumes_to_complete_global_count(tmp_path, monkeypatch):
    rows = [
        {"dataset_id": "a", "family": "trades", "sha256": "a" * 64,
         "trade_count": 2, "trade_count_exact": True, "release_repository": "owner/repo",
         "release_tag": "tag", "release_asset": "a.gz", "bytes": 1},
        {"dataset_id": "b", "family": "trades", "sha256": "b" * 64,
         "trade_count": 2, "trade_count_exact": True, "release_repository": "owner/repo",
         "release_tag": "tag", "release_asset": "b.gz", "bytes": 1},
    ]
    scanned_ids = []

    def fake_scan(row, temporary_root):
        scanned_ids.append(row["dataset_id"])
        path = temporary_root / f"{row['dataset_id']}.txt"
        path.write_text("shared\nunique-a\n" if row["dataset_id"] == "a" else "shared\nunique-b\n", encoding="utf-8")
        return {"exact": True, "trade_count_scanned": 2,
                "unique_trade_count": 2, "identity_path": str(path)}

    monkeypatch.setattr(global_counts, "INDEX_PATH", tmp_path / "index.json")
    monkeypatch.setattr(global_counts, "PATCH_PATH", tmp_path / "patch.json")
    monkeypatch.setattr(global_counts, "CHECKPOINT_PATH", tmp_path / "checkpoint.sqlite")
    monkeypatch.setattr(global_counts, "EXACT_COUNT_PATCH_PATH", tmp_path / "missing-counts.json")
    monkeypatch.setattr(
        global_counts,
        "_iter_trade_scan_rows",
        lambda _path: ([dict(row) for row in rows], len(rows), [], 0, "0" * 64),
    )
    monkeypatch.setattr(global_counts, "_patch_index_streaming", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(global_counts, "_persist_manifest_unique_counts", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(global_counts, "_scan_candidate", fake_scan)
    monkeypatch.setattr(sys, "argv", ["scan", "--limit", "1", "--workers", "1"])

    global_counts.main()
    first = json.loads(global_counts.PATCH_PATH.read_text(encoding="utf-8"))
    assert first["coverage_complete"] is False
    assert first["source_index_sha256"] == "0" * 64
    assert first["remaining_candidate_shards"] == 1
    assert first["global_unique_trade_count"] is None

    global_counts.main()
    final = json.loads(global_counts.PATCH_PATH.read_text(encoding="utf-8"))
    assert scanned_ids == ["a", "b"]
    assert final["schema"] == SCHEMA_V5
    assert final["source_index_sha256"] == "0" * 64
    assert final["counts"]["a"] == ["a" * 64, 2, 2, 2, 0, True]
    assert final["counts"]["b"] == ["b" * 64, 2, 2, 1, 1, True]
    assert global_unique_count_rows(final)["b"]["cross_shard_overlap_count"] == 1
    assert final["coverage_complete"] is True
    assert final["global_unique_trade_count"] == 3
    assert final["cross_shard_overlap_count"] == 1
    assert final["successful"] == 2


def test_parallel_scan_merges_in_dataset_order_despite_completion_order(tmp_path, monkeypatch):
    rows = [
        {"dataset_id": name, "family": "trades", "sha256": name * 64,
         "trade_count": 2, "trade_count_exact": True,
         "release_repository": "owner/repo", "release_tag": "tag",
         "release_asset": f"{name}.gz", "bytes": 1}
        for name in ("a", "b", "c")
    ]
    identities_by_id = {
        "a": ["id-a", "shared"],
        "b": ["id-b", "shared"],
        "c": ["id-b", "id-c"],
    }
    observed = []

    for run_number, delays in enumerate((
        {"a": 0.12, "b": 0.01, "c": 0.03},
        {"a": 0.01, "b": 0.12, "c": 0.03},
    )):
        run_root = tmp_path / f"run-{run_number}"
        run_root.mkdir()
        monkeypatch.setattr(global_counts, "ROOT", run_root)
        monkeypatch.setattr(global_counts, "INDEX_PATH", run_root / "index.json")
        monkeypatch.setattr(global_counts, "PATCH_PATH", run_root / "patch.json")
        monkeypatch.setattr(global_counts, "CHECKPOINT_PATH", run_root / "checkpoint.sqlite")
        monkeypatch.setattr(global_counts, "EXACT_COUNT_PATCH_PATH", run_root / "missing-counts.json")
        monkeypatch.setattr(
            global_counts,
            "_iter_trade_scan_rows",
            lambda _path: ([dict(row) for row in rows], len(rows), [], 0, "0" * 64),
        )
        monkeypatch.setattr(
            global_counts, "_patch_index_streaming", lambda *_args, **_kwargs: None,
        )
        monkeypatch.setattr(global_counts, "_persist_manifest_unique_counts", lambda *_args, **_kwargs: None)

        def fake_scan(row, temporary_root, *, delay_map=delays, identity_map=identities_by_id):
            time.sleep(delay_map[row["dataset_id"]])
            path = temporary_root / f"{row['dataset_id']}.txt"
            path.write_text("".join(f"{identity}\n" for identity in identity_map[row["dataset_id"]]),
                            encoding="utf-8")
            return {"exact": True, "trade_count_scanned": 2,
                    "unique_trade_count": 2, "identity_path": str(path)}

        monkeypatch.setattr(global_counts, "_scan_candidate", fake_scan)
        monkeypatch.setattr(sys, "argv", ["scan", "--limit", "3", "--workers", "3"])
        global_counts.main()
        result = json.loads(global_counts.PATCH_PATH.read_text(encoding="utf-8"))
        observed.append(result["counts"])
        assert result["merge_order_version"] == global_counts.MERGE_ORDER_VERSION
        assert result["coverage_complete"] is True

    assert observed[0] == observed[1]
    assert observed[0]["a"][3:5] == [2, 0]
    assert observed[0]["b"][3:5] == [1, 1]
    assert observed[0]["c"][3:5] == [1, 1]


def test_parallel_scan_stops_checkpoint_at_first_failed_dataset(tmp_path, monkeypatch):
    rows = [
        {"dataset_id": name, "family": "trades", "sha256": name * 64,
         "trade_count": 1, "trade_count_exact": True,
         "release_repository": "owner/repo", "release_tag": "tag",
         "release_asset": f"{name}.gz", "bytes": 1}
        for name in ("a", "b", "c")
    ]
    monkeypatch.setattr(global_counts, "ROOT", tmp_path)
    monkeypatch.setattr(global_counts, "INDEX_PATH", tmp_path / "index.json")
    monkeypatch.setattr(global_counts, "PATCH_PATH", tmp_path / "patch.json")
    monkeypatch.setattr(global_counts, "CHECKPOINT_PATH", tmp_path / "checkpoint.sqlite")
    monkeypatch.setattr(global_counts, "EXACT_COUNT_PATCH_PATH", tmp_path / "missing-counts.json")
    monkeypatch.setattr(
        global_counts,
        "_iter_trade_scan_rows",
        lambda _path: ([dict(row) for row in rows], len(rows), [], 0, "0" * 64),
    )
    monkeypatch.setattr(global_counts, "_patch_index_streaming", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(global_counts, "_persist_manifest_unique_counts", lambda *_args, **_kwargs: None)

    def fake_scan(row, temporary_root):
        if row["dataset_id"] == "a":
            time.sleep(0.08)
            raise OSError("source unavailable")
        path = temporary_root / f"{row['dataset_id']}.txt"
        path.write_text(f"identity-{row['dataset_id']}\n", encoding="utf-8")
        return {"exact": True, "trade_count_scanned": 1,
                "unique_trade_count": 1, "identity_path": str(path)}

    monkeypatch.setattr(global_counts, "_scan_candidate", fake_scan)
    monkeypatch.setattr(sys, "argv", ["scan", "--limit", "3", "--workers", "3"])
    global_counts.PATCH_PATH.write_text(
        json.dumps({
            "counts": {"failure_attempts": {"a": 99}},
            "failure_attempts": {"a": 4, "previous-shard": 2},
        }),
        encoding="utf-8",
    )
    global_counts.main()
    result = json.loads(global_counts.PATCH_PATH.read_text(encoding="utf-8"))
    assert result["attempted"] == 1
    assert result["selected_for_attempt"] == 3
    assert result["unscanned_candidate_shards"] == 2
    assert result["successful"] == 0
    assert result["coverage_complete"] is False
    assert result["failure_attempts"] == {"a": 5, "previous-shard": 2}

    database = global_counts._open_checkpoint(global_counts.CHECKPOINT_PATH, [dict(row) for row in rows])
    assert database.execute("SELECT COUNT(*) FROM completed").fetchone()[0] == 0
    assert database.execute("SELECT COUNT(*) FROM ids").fetchone()[0] == 0
    database.close()


def test_checkpoint_refuses_existing_legacy_completion_order(tmp_path):
    row = {"dataset_id": "a", "sha256": "a" * 64, "trade_count": 1,
           "trade_count_exact": True}
    checkpoint = tmp_path / "legacy.sqlite"
    database = global_counts._open_checkpoint(checkpoint, [row])
    identities = tmp_path / "ids.txt"
    identities.write_text("trade-a\n", encoding="utf-8")
    global_counts._merge_checkpoint_shard(database, row, {
        "exact": True, "trade_count_scanned": 1,
        "unique_trade_count": 1, "identity_path": str(identities),
    })
    database.execute("DELETE FROM metadata WHERE key='merge_order_version'")
    database.commit()
    database.close()

    with pytest.raises(ValueError, match="merge order is unverified"):
        global_counts._open_checkpoint(checkpoint, [row])


def test_streaming_index_patch_updates_partitioned_catalog_without_rehydrating(tmp_path):
    index_path = tmp_path / "DATA_INDEX.json"
    logical = {
        "schema": "alina.data_index.v1",
        "release_repository_default": "owner/repo",
        "shards": [
            {"dataset_id": "a", "family": "trades", "sha256": "a" * 64,
             "unique_trade_count": None,
             "fixture_padding": "x" * 600},
            {"dataset_id": "b", "family": "trades", "sha256": "b" * 64,
             "unique_trade_count": None,
             "fixture_padding": "x" * 600},
        ],
    }
    save_index(index_path, logical, max_inline_bytes=1024, max_partition_bytes=1024)
    original_root = json.loads(index_path.read_text(encoding="utf-8"))
    source_root_sha256 = global_counts.hashlib.sha256(index_path.read_bytes()).hexdigest()
    original_parts = {
        descriptor["path"]: (tmp_path / descriptor["path"]).read_bytes()
        for descriptor in original_root["partitions"]
    }

    global_counts._patch_index_streaming(index_path, {
        "a": {"asset_sha256": "a" * 64, "unique_trade_count": 7,
              "unique_trade_count_exact": True},
    }, expected_root_sha256=source_root_sha256)

    updated = read_index(index_path)
    assert updated["shards"][0]["unique_trade_count"] == 7
    assert updated["shards"][0]["unique_trade_count_exact"] is True
    assert updated["shards"][1]["unique_trade_count"] is None
    for relative, content in original_parts.items():
        assert (tmp_path / relative).read_bytes() == content
    updated_descriptors = json.loads(index_path.read_text(encoding="utf-8"))["partitions"]
    assert updated_descriptors[0]["path"].endswith(
        f"-{updated_descriptors[0]['sha256']}.json"
    )
    assert updated_descriptors[1]["path"] == original_root["partitions"][1]["path"]


def test_streaming_index_patch_root_failure_preserves_old_catalog(tmp_path, monkeypatch):
    import os

    index_path = tmp_path / "DATA_INDEX.json"
    original = {
        "schema": "alina.data_index.v1",
        "shards": [
            {"dataset_id": "a", "family": "trades", "sha256": "a" * 64,
             "unique_trade_count": None,
             "fixture_padding": "x" * 600},
            {"dataset_id": "b", "family": "trades", "sha256": "b" * 64,
             "unique_trade_count": None,
             "fixture_padding": "x" * 600},
        ],
    }
    save_index(index_path, original, max_inline_bytes=1024, max_partition_bytes=1024)
    original_root = index_path.read_bytes()
    original_parts = {
        descriptor["path"]: (tmp_path / descriptor["path"]).read_bytes()
        for descriptor in json.loads(original_root)["partitions"]
    }
    real_replace = os.replace

    def fail_root_replace(source, destination):
        if Path(destination) == index_path:
            raise OSError("simulated root publication interruption")
        return real_replace(source, destination)

    monkeypatch.setattr(os, "replace", fail_root_replace)
    with pytest.raises(OSError, match="simulated root publication interruption"):
        global_counts._patch_index_streaming(index_path, {
            "a": {"asset_sha256": "a" * 64, "unique_trade_count": 5,
                  "unique_trade_count_exact": True},
        })

    assert index_path.read_bytes() == original_root
    assert read_index(index_path) == original
    for relative, content in original_parts.items():
        assert (tmp_path / relative).read_bytes() == content


@pytest.mark.parametrize("partitioned", [False, True])
def test_streaming_index_patch_rejects_stale_asset_evidence(tmp_path, partitioned):
    index_path = tmp_path / "DATA_INDEX.json"
    logical = {
        "schema": "alina.data_index.v1",
        "shards": [
            {"dataset_id": "a", "family": "trades", "sha256": "a" * 64,
             "unique_trade_count": None, "fixture_padding": "x" * 1200},
        ],
    }
    if partitioned:
        save_index(index_path, logical, max_inline_bytes=1024, max_partition_bytes=2048)
    else:
        index_path.write_text(
            json.dumps(logical, sort_keys=True, separators=(",", ":")) + "\n",
            encoding="utf-8",
        )
    original_root = index_path.read_bytes()

    with pytest.raises(ValueError, match="GLOBAL_UNIQUE_STALE_ASSET_EVIDENCE"):
        global_counts._patch_index_streaming(index_path, {
            "a": {"asset_sha256": "f" * 64, "unique_trade_count": 7,
                  "unique_trade_count_exact": True},
        })

    assert index_path.read_bytes() == original_root
    assert read_index(index_path)["shards"] == logical["shards"]


def test_streaming_index_patch_refuses_catalog_changed_after_scan(tmp_path):
    index_path = tmp_path / "DATA_INDEX.json"
    logical = {
        "schema": "alina.data_index.v1",
        "shards": [
            {"dataset_id": "a", "family": "trades", "sha256": "a" * 64,
             "unique_trade_count": None},
        ],
    }
    index_path.write_text(json.dumps(logical), encoding="utf-8")
    scan_root_sha256 = global_counts.hashlib.sha256(index_path.read_bytes()).hexdigest()
    concurrent = {**logical, "collection_epoch": 4}
    index_path.write_text(json.dumps(concurrent), encoding="utf-8")
    current_root = index_path.read_bytes()

    with pytest.raises(ValueError, match="GLOBAL_UNIQUE_SOURCE_INDEX_CHANGED_BEFORE_PUBLISH"):
        global_counts._patch_index_streaming(
            index_path,
            {"a": {"asset_sha256": "a" * 64, "unique_trade_count": 1}},
            expected_root_sha256=scan_root_sha256,
        )

    assert index_path.read_bytes() == current_root


def test_trade_scan_rows_rejects_index_change_during_enumeration(tmp_path, monkeypatch):
    index_path = tmp_path / "DATA_INDEX.json"
    original = {"schema": "alina.data_index.v1", "shards": []}
    index_path.write_text(json.dumps(original), encoding="utf-8")
    concurrent = {**original, "collection_epoch": 5}
    real_iter_index_rows = global_counts.iter_index_rows

    def enumerate_then_simulate_collection_update(path):
        yield from real_iter_index_rows(path)
        index_path.write_text(json.dumps(concurrent), encoding="utf-8")

    monkeypatch.setattr(global_counts, "iter_index_rows", enumerate_then_simulate_collection_update)

    with pytest.raises(ValueError, match="GLOBAL_UNIQUE_SOURCE_INDEX_CHANGED_DURING_SCAN"):
        global_counts._iter_trade_scan_rows(index_path)


def test_trade_scan_rows_returns_hash_of_exact_source_root(tmp_path):
    index_path = tmp_path / "DATA_INDEX.json"
    source_bytes = json.dumps(
        {"schema": "alina.data_index.v1", "shards": []},
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    index_path.write_bytes(source_bytes)

    result = global_counts._iter_trade_scan_rows(index_path)

    assert result[:4] == ([], 0, [], 0)
    assert result[4] == global_counts.hashlib.sha256(source_bytes).hexdigest()


def test_streaming_index_patch_does_not_overwrite_concurrent_root_update(
    tmp_path, monkeypatch,
):
    index_path = tmp_path / "DATA_INDEX.json"
    original = {
        "schema": "alina.data_index.v1",
        "shards": [
            {"dataset_id": "a", "family": "trades", "sha256": "a" * 64,
             "unique_trade_count": None,
             "fixture_padding": "x" * 600},
            {"dataset_id": "b", "family": "trades", "sha256": "b" * 64,
             "unique_trade_count": None,
             "fixture_padding": "x" * 600},
        ],
    }
    save_index(index_path, original, max_inline_bytes=1024, max_partition_bytes=1024)
    original_partitions = json.loads(index_path.read_text(encoding="utf-8"))["partitions"]
    original_paths = [descriptor["path"] for descriptor in original_partitions]
    real_publish = global_counts._publish_immutable_partition
    concurrent_update_applied = False

    def publish_then_simulate_collector_update(destination, content):
        nonlocal concurrent_update_applied
        result = real_publish(destination, content)
        concurrent_root = json.loads(index_path.read_text(encoding="utf-8"))
        concurrent_root["collection_epoch"] = 99
        index_path.write_text(
            json.dumps(concurrent_root, sort_keys=True, separators=(",", ":")) + "\n",
            encoding="utf-8",
        )
        concurrent_update_applied = True
        return result

    monkeypatch.setattr(
        global_counts, "_publish_immutable_partition", publish_then_simulate_collector_update,
    )

    with pytest.raises(ValueError, match="PARTITION_PARITY_CONCURRENT_ROOT_CHANGE"):
        global_counts._patch_index_streaming(index_path, {
            "a": {"asset_sha256": "a" * 64, "unique_trade_count": 7,
                  "unique_trade_count_exact": True},
        })

    current_root = json.loads(index_path.read_text(encoding="utf-8"))
    assert concurrent_update_applied is True
    assert current_root["collection_epoch"] == 99
    assert [descriptor["path"] for descriptor in current_root["partitions"]] == original_paths
    reconstructed = read_index(index_path)
    assert reconstructed["collection_epoch"] == 99
    assert reconstructed["shards"] == original["shards"]


@pytest.mark.parametrize("manifest_sha, should_update", [
    ("a" * 64, True),
    ("b" * 64, False),
])
def test_manifest_unique_count_write_requires_matching_asset_hash(
    tmp_path, monkeypatch, manifest_sha, should_update,
):
    monkeypatch.setattr(global_counts, "ROOT", tmp_path)
    manifest_path = tmp_path / "datasets" / "manifest.json"
    manifest_path.parent.mkdir()
    original = {
        "dataset_id": "dataset-a",
        "sha256": manifest_sha,
        "quality_status": "SAFE",
    }
    manifest_path.write_text(json.dumps(original), encoding="utf-8")

    global_counts._persist_manifest_unique_counts(
        {
            "dataset_id": "dataset-a",
            "manifest_path": "datasets/manifest.json",
            "sha256": "a" * 64,
        },
        unique_count=3,
        exact=True,
    )

    observed = json.loads(manifest_path.read_text(encoding="utf-8"))
    if should_update:
        assert observed["unique_trade_count"] == 3
        assert observed["unique_trade_count_exact"] is True
    else:
        assert manifest_path.read_text(encoding="utf-8") == json.dumps(original)


def test_manifest_unique_count_write_preserves_concurrent_collector_update(
    tmp_path, monkeypatch,
):
    monkeypatch.setattr(global_counts, "ROOT", tmp_path)
    manifest_path = tmp_path / "datasets" / "manifest.json"
    manifest_path.parent.mkdir()
    original = {"dataset_id": "dataset-a", "sha256": "a" * 64, "quality_status": "SAFE"}
    concurrent = {**original, "quality_status": "UPDATED_BY_COLLECTOR"}
    original_bytes = json.dumps(original).encode("utf-8")
    concurrent_bytes = json.dumps(concurrent).encode("utf-8")
    manifest_path.write_bytes(original_bytes)
    real_read_bytes = Path.read_bytes
    read_count = 0

    def update_between_read_and_replace(path):
        nonlocal read_count
        if path == manifest_path:
            read_count += 1
            if read_count == 2:
                path.write_bytes(concurrent_bytes)
                return concurrent_bytes
        return real_read_bytes(path)

    monkeypatch.setattr(Path, "read_bytes", update_between_read_and_replace)
    global_counts._persist_manifest_unique_counts(
        {
            "dataset_id": "dataset-a",
            "manifest_path": "datasets/manifest.json",
            "sha256": "a" * 64,
        },
        unique_count=3,
        exact=True,
    )

    assert real_read_bytes(manifest_path) == concurrent_bytes
    assert json.loads(real_read_bytes(manifest_path)).get("unique_trade_count") is None


def test_streaming_index_patch_repartitions_when_evidence_grows_rows(tmp_path):
    index_path = tmp_path / "DATA_INDEX.json"
    logical = {
        "schema": "alina.data_index.v1",
        "shards": [
            {"dataset_id": f"dataset-{number}", "family": "trades",
             "sha256": f"{number:x}" * 64, "note": "x" * 40}
            for number in range(6)
        ],
    }
    root, parts = partition_index(logical, max_partition_bytes=400)
    (tmp_path / "data-index-parts").mkdir()
    index_path.write_bytes(
        (json.dumps(root, sort_keys=True, separators=(",", ":")) + "\n").encode()
    )
    for relative, data in parts.items():
        target = tmp_path / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)

    global_counts._patch_index_streaming(index_path, {
        f"dataset-{number}": {
            "asset_sha256": f"{number:x}" * 64,
            "unique_trade_count": number,
            "unique_trade_count_exact": True,
            "identity_version": "v3",
        }
        for number in range(6)
    })

    updated = read_index(index_path)
    assert len(updated["shards"]) == 6
    assert [row["unique_trade_count"] for row in updated["shards"]] == list(range(6))


def test_scan_candidate_extracts_exact_identities_without_global_state(tmp_path, monkeypatch):
    asset = tmp_path / "asset.jsonl.gz"
    raw = {
        "topic": "publicTrade.BTCUSDT",
        "data": [
            {"i": "a", "T": 1, "p": "10", "v": "1", "S": "Buy", "s": "BTCUSDT"},
            {"i": "b", "T": 2, "p": "11", "v": "2", "S": "Sell", "s": "BTCUSDT"},
            {"i": "a", "T": 1, "p": "10", "v": "1", "S": "Buy", "s": "BTCUSDT"},
        ],
    }
    with gzip.open(asset, "wt", encoding="utf-8") as handle:
        handle.write(json.dumps({"raw_payload": json.dumps(raw)}) + "\n")
    monkeypatch.setattr(global_counts, "_download", lambda row, destination: asset)
    row = {
        "dataset_id": "sample",
        "venue": "bybit",
        "family": "trades",
        "symbol": "BTCUSDT",
    }

    result = global_counts._scan_candidate(row, tmp_path)

    assert result["dataset_id"] == "sample"
    assert result["trade_count_scanned"] == 3
    assert result["unique_trade_count"] == 2
    assert result["exact"] is True
    identities = result["identity_path"]
    with open(identities, encoding="utf-8") as handle:
        rows = [line.strip() for line in handle if line.strip()]
    assert rows == sorted(set(rows))
    assert len(rows) == 2


def test_scan_candidate_rejects_jsonl_records_above_memory_bound(tmp_path, monkeypatch):
    asset = tmp_path / "oversized.jsonl.gz"
    with gzip.open(asset, "wb") as handle:
        handle.write(b'{"raw_payload":"' + (b"x" * 128) + b'"}\n')
    monkeypatch.setattr(global_counts, "MAX_JSONL_RECORD_BYTES", 64)
    monkeypatch.setattr(global_counts, "_download", lambda _row, _destination: asset)

    with pytest.raises(ValueError, match="oversized JSONL record"):
        global_counts._scan_candidate(
            {"dataset_id": "oversized", "family": "trades"},
            tmp_path / "scan",
        )


@pytest.mark.parametrize(
    ("record", "error"),
    [
        (b"null\n", "non-object JSONL record"),
        (b"\n", "Expecting value"),
    ],
)
def test_scan_candidate_fails_closed_on_non_object_or_blank_records(
    tmp_path,
    monkeypatch,
    record,
    error,
):
    asset = tmp_path / "invalid.jsonl.gz"
    with gzip.open(asset, "wb") as handle:
        handle.write(record)
    monkeypatch.setattr(global_counts, "_download", lambda _row, _destination: asset)

    with pytest.raises(ValueError, match=error):
        global_counts._scan_candidate(
            {"dataset_id": "invalid", "family": "trades"},
            tmp_path / "scan",
        )


def test_scan_candidate_bounds_workspace_for_long_release_asset_names(tmp_path, monkeypatch):
    asset = tmp_path / "asset.jsonl.gz"
    with gzip.open(asset, "wt", encoding="utf-8") as handle:
        handle.write(json.dumps({
            "raw_payload": {
                "time": 123,
                "px": "100.5",
                "sz": "2",
                "side": "B",
                "coin": "BTC",
                "hash": "0xabc",
                "oid": 7,
            },
        }) + "\n")
    seen: list[Path] = []

    def fake_download(_row, destination):
        seen.append(destination)
        return asset

    monkeypatch.setattr(global_counts, "_download", fake_download)
    result = global_counts._scan_candidate(
        {
            "dataset_id": "dataset-" + "x" * 240,
            "venue": "hyperliquid",
            "family": "copy_vault_fills",
            "symbol": "BTC",
        },
        tmp_path / "alina-global-unique-very-long-temporary-root",
    )

    assert result["exact"] is True
    assert len(seen) == 1
    assert len(str(seen[0] / asset.name)) < 260


def test_unique_candidate_excludes_non_trade_zero_count_assets():
    base = {
        "dataset_id": "x",
        "trade_count_exact": True,
        "release_repository": "owner/repo",
        "release_tag": "tag",
        "release_asset": "asset.jsonl.gz",
        "sha256": "a" * 64,
        "bytes": 1,
    }
    assert global_counts._unique_candidate({**base, "family": "bbo", "trade_count": 0}) is False
    assert global_counts._unique_candidate({**base, "family": "l2Book", "trade_count": 100}) is False
    assert global_counts._unique_candidate({**base, "family": "trades", "trade_count": 0}) is False
    assert global_counts._unique_candidate({**base, "family": "trades", "trade_count": 1}) is True


def test_compact_scan_row_preserves_read_only_mapping_contract():
    values = {
        "dataset_id": "trade-1",
        "family": "trades",
        "trade_count": 4,
        "trade_count_exact": True,
        "sha256": "a" * 64,
        "release_tag": "release-1",
    }
    row = global_counts._CompactScanRow(values)

    expected = {key: values.get(key) for key in global_counts._SCAN_ROW_KEYS}
    assert dict(row) == expected
    assert row["dataset_id"] == "trade-1"
    assert row.get("missing", "fallback") == "fallback"
    assert global_counts._unique_candidate(row) is False  # incomplete immutable release identity
    assert not hasattr(row, "__dict__")


def test_native_trade_keys_support_normalized_hyperliquid_fill_without_raw_envelope():
    record = {
        "raw_payload": {
            "time": 123,
            "px": "100.5",
            "sz": "2",
            "side": "B",
            "coin": "BTC",
            "hash": "0xabc",
            "oid": 7,
        }
    }
    keys = global_counts._native_trade_keys(
        record, venue="hyperliquid", family="copy_vault_fills", symbol="BTC"
    )
    assert keys is not None
    assert len(keys) == 1
    assert keys[0].startswith("hyperliquid|copy_vault_fills|BTC|fallback|123|100.5|2|B|BTC|")


def test_native_trade_keys_support_normalized_binance_official_aggtrade_as_trades():
    record = {
        "raw_payload": {
            "agg_trade_id": "123456",
            "price": "101.25",
            "quantity": "0.75",
            "first_trade_id": "100",
            "last_trade_id": "102",
            "transact_time": 1790000000123,
            "is_buyer_maker": False,
        }
    }
    keys = global_counts._native_trade_keys(
        record, venue="binance", family="trades", symbol="BTCUSDT"
    )
    assert keys == ["binance|trades|BTCUSDT|a|123456"]


def test_native_trade_keys_support_binance_archive_list_payload():
    record = {
        "raw_payload": [
            {"id": 11, "time": 1000, "price": "10", "qty": "1", "side": "BUY"},
            {"id": 12, "time": 1001, "price": "11", "qty": "2", "side": "SELL"},
        ]
    }
    keys = global_counts._native_trade_keys(
        record, venue="binance", family="trades", symbol="BTCUSDT"
    )
    assert keys == [
        "binance|trades|BTCUSDT|t|11",
        "binance|trades|BTCUSDT|t|12",
    ]


def test_native_trade_keys_support_normalized_copy_vault_fill_ts_ms():
    record = {
        "raw_payload": {
            "vault": "0xabc",
            "ts_ms": 1790000000123,
            "coin": "BTC",
            "px": 101.25,
            "sz": 0.75,
            "signe": 1,
            "dir": "Open Long",
            "hash": "0xfeed",
            "oid": 42,
            "start_position": 0.0,
        }
    }
    keys = global_counts._native_trade_keys(
        record, venue="hyperliquid", family="copy_vault_fills", symbol="BTC"
    )
    assert keys is not None
    assert len(keys) == 1
    assert keys[0].startswith(
        "hyperliquid|copy_vault_fills|BTC|fallback|1790000000123|101.25|0.75|Open Long|BTC|"
    )


def test_native_trade_keys_support_gate_native_trade_id() -> None:
    record = {
        "raw_payload": {
            "channel": "futures.trades",
            "result": [
                {
                    "id": 987654321,
                    "create_time_ms": 1790991018232,
                    "contract": "ETH_USDT",
                    "price": "3500.1",
                    "size": 3,
                    "side": "sell",
                }
            ],
        }
    }
    keys = global_counts._native_trade_keys(
        record,
        venue="gate",
        family="trades",
        symbol="ETH_USDT",
    )
    assert keys == ["gate|trades|ETH_USDT|id|987654321"]


def test_native_trade_keys_fail_closed_when_composite_is_ambiguous():
    keys = global_counts._native_trade_keys(
        {"raw_payload": {"time": 1, "px": "10"}},
        venue="hyperliquid",
        family="fills",
        symbol="BTC",
    )
    assert keys is None

def test_native_trade_keys_support_hyperliquid_userfills_nested_envelope():
    record = {
        "raw_payload": {
            "channel": "userFills",
            "data": {
                "user": "0xabc",
                "isSnapshot": False,
                "fills": [
                    {"tid": 101, "time": 10, "px": "100", "sz": "1", "side": "B", "coin": "BTC"},
                    {"tid": 102, "time": 11, "px": "101", "sz": "2", "side": "A", "coin": "BTC"},
                ],
            },
        }
    }
    keys = global_counts._native_trade_keys(
        record, venue="hyperliquid", family="copy_vault_fills", symbol="0xabc"
    )
    assert keys == [
        "hyperliquid|copy_vault_fills|0xabc|tid|101",
        "hyperliquid|copy_vault_fills|0xabc|tid|102",
    ]



def test_bybit_archive_trd_match_id_is_canonical_native_identity():
    row = {
        "raw_payload": {
            "timestamp": "1790000000.125",
            "symbol": "BTCUSDT",
            "side": "Buy",
            "size": "0.1",
            "price": "100.5",
            "trdMatchID": "archive-match-123",
        }
    }
    keys = global_counts._native_trade_keys(
        row,
        venue="bybit",
        family="trades",
        symbol="BTCUSDT",
    )
    assert keys == ["bybit|trades|BTCUSDT|i|archive-match-123"]



def test_restore_exact_trade_count_rows_recovers_corrupted_index(tmp_path):
    patch=tmp_path/"TRADE_COUNT_PATCH.json"
    patch.write_text(
        json.dumps({
            "counts":{
                "bybit-archive":{
                    "asset_sha256":"a"*64,
                    "trade_count":190000,
                    "trade_count_exact":True,
                }
            }
        }),
        encoding="utf-8",
    )
    rows=[{
        "dataset_id":"bybit-archive",
        "family":"trades",
        "sha256":"a"*64,
        "trade_count":0,
        "trade_count_exact":False,
        "release_repository":"owner/repo",
        "release_tag":"tag",
        "release_asset":"asset.jsonl.gz",
        "bytes":1,
    }]
    restored=global_counts._restore_exact_trade_count_rows(rows,patch_path=patch)
    assert restored==1
    assert rows[0]["trade_count"]==190000
    assert rows[0]["trade_count_exact"] is True
    assert global_counts._unique_candidate(rows[0]) is True


def test_restore_exact_trade_count_rows_rejects_sha_mismatch(tmp_path):
    patch=tmp_path/"TRADE_COUNT_PATCH.json"
    patch.write_text(
        json.dumps({
            "counts":{
                "x":{
                    "asset_sha256":"b"*64,
                    "trade_count":42,
                    "trade_count_exact":True,
                }
            }
        }),
        encoding="utf-8",
    )
    rows=[{"dataset_id":"x","family":"trades","sha256":"a"*64,
           "trade_count":0,"trade_count_exact":False}]
    assert global_counts._restore_exact_trade_count_rows(rows,patch_path=patch)==0
    assert rows[0]["trade_count_exact"] is False



def test_scope_counts_missing_exact_trade_rows_as_unproven():
    rows = [
        {"dataset_id": "a", "family": "trades", "trade_count_exact": True, "trade_count": 1},
        {"dataset_id": "b", "family": "trades", "trade_count_exact": False, "trade_count": 0},
        {"dataset_id": "c", "family": "bbo", "trade_count_exact": False, "trade_count": 0},
    ]
    trade_rows = [
        row for row in rows
        if str(row.get("family") or "").lower() in global_counts.TRADE_FAMILIES
    ]
    unproven = [
        row["dataset_id"] for row in trade_rows
        if row.get("trade_count_exact") is not True
    ]
    assert len(trade_rows) == 2
    assert unproven == ["b"]
