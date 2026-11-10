from __future__ import annotations

import gzip
import json
import sys
from pathlib import Path
from pathlib import Path

import pytest

from tools import backfill_global_unique_trade_counts as global_counts
from tools.partitioned_data_index import partition_index, read_index, save_index


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
        lambda _path: ([dict(row) for row in rows], len(rows), [], 0),
    )
    monkeypatch.setattr(global_counts, "_patch_index_streaming", lambda *_args: None)
    monkeypatch.setattr(global_counts, "_persist_manifest_unique_counts", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(global_counts, "_scan_candidate", fake_scan)
    monkeypatch.setattr(sys, "argv", ["scan", "--limit", "1", "--workers", "1"])

    global_counts.main()
    first = json.loads(global_counts.PATCH_PATH.read_text(encoding="utf-8"))
    assert first["coverage_complete"] is False
    assert first["remaining_candidate_shards"] == 1
    assert first["global_unique_trade_count"] is None

    global_counts.main()
    final = json.loads(global_counts.PATCH_PATH.read_text(encoding="utf-8"))
    assert scanned_ids == ["a", "b"]
    assert final["coverage_complete"] is True
    assert final["global_unique_trade_count"] == 3
    assert final["cross_shard_overlap_count"] == 1
    assert final["successful"] == 2


def test_streaming_index_patch_updates_partitioned_catalog_without_rehydrating(tmp_path):
    index_path = tmp_path / "DATA_INDEX.json"
    logical = {
        "schema": "alina.data_index.v1",
        "release_repository_default": "owner/repo",
        "shards": [
            {"dataset_id": "a", "family": "trades", "unique_trade_count": None},
            {"dataset_id": "b", "family": "trades", "unique_trade_count": None},
        ],
    }
    save_index(index_path, logical, max_partition_bytes=1024)

    global_counts._patch_index_streaming(index_path, {
        "a": {"unique_trade_count": 7, "unique_trade_count_exact": True},
    })

    updated = read_index(index_path)
    assert updated["shards"][0]["unique_trade_count"] == 7
    assert updated["shards"][0]["unique_trade_count_exact"] is True
    assert updated["shards"][1]["unique_trade_count"] is None


def test_streaming_index_patch_repartitions_when_evidence_grows_rows(tmp_path):
    index_path = tmp_path / "DATA_INDEX.json"
    logical = {
        "schema": "alina.data_index.v1",
        "shards": [
            {"dataset_id": f"dataset-{number}", "family": "trades", "note": "x" * 40}
            for number in range(6)
        ],
    }
    root, parts = partition_index(logical, max_partition_bytes=256)
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
