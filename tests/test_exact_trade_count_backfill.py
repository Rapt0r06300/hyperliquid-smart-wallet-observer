from __future__ import annotations

import gzip
import hashlib
import json

import pytest

from tools import backfill_exact_trade_counts as exact
from tools.backfill_exact_trade_counts import (
    IDENTITY_VERSION,
    _candidate,
    _candidate_priority,
    inspect_asset,
)


def _write(path, rows):
    with gzip.open(path, "wt", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row) + "\n")


def _index_row(path, *, venue, family="trades", symbol="BTCUSDT"):
    return {
        "venue": venue,
        "family": family,
        "symbol": symbol,
        "bytes": path.stat().st_size,
        "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
    }


def test_bybit_batch_counts_all_underlying_trades_and_unique_ids(tmp_path):
    path = tmp_path / "bybit.jsonl.gz"
    raw = {
        "topic": "publicTrade.BTCUSDT",
        "data": [
            {"i": "a", "T": 1, "p": "10", "v": "1", "S": "Buy", "s": "BTCUSDT"},
            {"i": "b", "T": 2, "p": "11", "v": "2", "S": "Sell", "s": "BTCUSDT"},
        ],
    }
    _write(
        path,
        [{
            "parsed_summary": {"event_count": 2},
            "raw_payload": json.dumps(raw),
        }],
    )
    out = inspect_asset(path, _index_row(path, venue="bybit"))
    assert out["trade_count"] == 2
    assert out["trade_count_exact"] is True
    assert out["unique_trade_count"] == 2
    assert out["unique_trade_count_exact"] is True


def test_binance_duplicate_native_id_is_deduped_within_shard(tmp_path):
    path = tmp_path / "binance.jsonl.gz"
    row = {
        "parsed_summary": {},
        "raw_payload": json.dumps({"e": "trade", "s": "BTCUSDT", "t": 42}),
    }
    _write(path, [row, row])
    out = inspect_asset(path, _index_row(path, venue="binance"))
    assert out["trade_count"] == 2
    assert out["unique_trade_count"] == 1
    assert out["unique_trade_count_exact"] is True


def test_unknown_trade_shape_never_fabricates_unique_count(tmp_path):
    path = tmp_path / "unknown.jsonl.gz"
    _write(path, [{"parsed_summary": {"event_count": 3}, "raw_payload": "{}"}])
    out = inspect_asset(path, _index_row(path, venue="unknown"))
    assert out["trade_count"] == 3
    assert out["unique_trade_count"] is None
    assert out["unique_trade_count_exact"] is False


def test_candidate_priority_prefers_replayable_safe_before_rejected():
    replayable = {"quality_status": "SAFE", "replay_compatible": True, "end_ts_ms": 300}
    safe = {"quality_status": "SAFE", "replay_compatible": False, "end_ts_ms": 400}
    partial = {"quality_status": "PARTIAL", "replay_compatible": False, "end_ts_ms": 500}
    rejected = {"quality_status": "REJECT", "replay_compatible": False, "end_ts_ms": 600}
    rows = [rejected, partial, safe, replayable]
    assert sorted(rows, key=_candidate_priority) == [replayable, safe, partial, rejected]


def test_bybit_official_archive_prefers_trd_match_id_over_composite(tmp_path):
    path = tmp_path / "bybit-archive.jsonl.gz"
    _write(path, [
        {
            "exchange_ts_ms": 1000,
            "raw_payload": {
                "timestamp": "1.000",
                "symbol": "BTCUSDT",
                "side": "Buy",
                "size": "0.1",
                "price": "100",
                "trdMatchID": "match-a",
            },
        },
        {
            "exchange_ts_ms": 1000,
            "raw_payload": {
                "timestamp": "1.000",
                "symbol": "BTCUSDT",
                "side": "Buy",
                "size": "0.1",
                "price": "100",
                "trdMatchID": "match-b",
            },
        },
    ])
    out = inspect_asset(path, _index_row(path, venue="bybit"))
    assert out["trade_count"] == 2
    assert out["unique_trade_count"] == 2
    assert out["unique_trade_count_exact"] is True



def test_bybit_v2_exact_patch_is_requeued_for_native_identity_upgrade():
    row = {
        "dataset_id": "bybit-archive",
        "venue": "bybit",
        "family": "trades",
        "sha256": "a" * 64,
        "bytes": 100,
        "release_repository": "Rapt0r06300/hyperliquid-smart-wallet-observer",
        "release_tag": "archive-test",
        "release_asset": "bybit.jsonl.gz",
        "trade_count": 190000,
        "trade_count_exact": True,
    }
    counts = {
        "bybit-archive": {
            "asset_sha256": "a" * 64,
            "trade_count": 190000,
            "trade_count_exact": True,
            "unique_trade_count": 138698,
            "unique_trade_count_exact": True,
            "unique_identity_method": "full_native_or_deterministic_composite_string_v2",
        }
    }
    assert _candidate(row, counts) is True
    counts["bybit-archive"]["unique_identity_method"] = IDENTITY_VERSION
    assert _candidate(row, counts) is False


def test_non_bybit_sha_matched_exact_patch_is_not_needlessly_rescanned():
    row = {
        "dataset_id": "binance-archive",
        "venue": "binance",
        "family": "trades",
        "sha256": "b" * 64,
        "bytes": 100,
        "release_repository": "Rapt0r06300/hyperliquid-smart-wallet-observer",
        "release_tag": "archive-test",
        "release_asset": "binance.jsonl.gz",
        "trade_count": 0,
        "trade_count_exact": False,
    }
    counts = {
        "binance-archive": {
            "asset_sha256": "b" * 64,
            "trade_count": 200000,
            "trade_count_exact": True,
            "unique_trade_count": 200000,
            "unique_trade_count_exact": True,
            "unique_identity_method": "full_native_or_deterministic_composite_string_v2",
        }
    }
    assert _candidate(row, counts) is False


@pytest.mark.parametrize("result_sha, should_update", [("a" * 64, True), ("b" * 64, False)])
def test_exact_count_manifest_update_requires_matching_asset_sha(
    tmp_path, monkeypatch, result_sha, should_update,
):
    monkeypatch.setattr(exact, "ROOT", tmp_path)
    manifest_path = tmp_path / "datasets" / "manifest.json"
    manifest_path.parent.mkdir()
    original = {"dataset_id": "dataset-a", "sha256": "a" * 64, "quality_status": "SAFE"}
    manifest_path.write_text(json.dumps(original), encoding="utf-8")

    exact._persist_manifest_counts(
        {
            "dataset_id": "dataset-a",
            "manifest_path": "datasets/manifest.json",
            "sha256": "a" * 64,
        },
        {
            "asset_sha256": result_sha,
            "trade_count": 5,
            "trade_count_exact": True,
        },
    )

    observed = json.loads(manifest_path.read_text(encoding="utf-8"))
    if should_update:
        assert observed["trade_count"] == 5
        assert observed["trade_count_exact"] is True
    else:
        assert observed == original


def test_exact_count_manifest_update_preserves_concurrent_collector_change(
    tmp_path, monkeypatch,
):
    from pathlib import Path

    monkeypatch.setattr(exact, "ROOT", tmp_path)
    manifest_path = tmp_path / "datasets" / "manifest.json"
    manifest_path.parent.mkdir()
    original = {"dataset_id": "dataset-a", "sha256": "a" * 64, "quality_status": "SAFE"}
    concurrent = {**original, "quality_status": "UPDATED_BY_COLLECTOR"}
    original_bytes = json.dumps(original).encode("utf-8")
    concurrent_bytes = json.dumps(concurrent).encode("utf-8")
    manifest_path.write_bytes(original_bytes)
    real_read_bytes = Path.read_bytes
    read_count = 0

    def update_before_atomic_replace(path):
        nonlocal read_count
        if path == manifest_path:
            read_count += 1
            if read_count == 2:
                path.write_bytes(concurrent_bytes)
                return concurrent_bytes
        return real_read_bytes(path)

    monkeypatch.setattr(Path, "read_bytes", update_before_atomic_replace)
    exact._persist_manifest_counts(
        {
            "dataset_id": "dataset-a",
            "manifest_path": "datasets/manifest.json",
            "sha256": "a" * 64,
        },
        {
            "asset_sha256": "a" * 64,
            "trade_count": 5,
            "trade_count_exact": True,
        },
    )

    assert real_read_bytes(manifest_path) == concurrent_bytes


def test_exact_count_backfill_refuses_catalog_change_during_asset_scan(tmp_path, monkeypatch):
    index_path = tmp_path / "catalog" / "DATA_INDEX.json"
    index_path.parent.mkdir()
    row = {
        "dataset_id": "dataset-a",
        "family": "trades",
        "venue": "binance",
        "sha256": "a" * 64,
        "bytes": 10,
        "release_repository": "owner/repo",
        "release_tag": "release-a",
        "release_asset": "asset-a.gz",
        "trade_count_exact": False,
    }
    original = {"schema": "alina.data_index.v1", "shards": [row]}
    index_path.write_text(json.dumps(original), encoding="utf-8")
    monkeypatch.setattr(exact, "INDEX_PATH", index_path)
    monkeypatch.setattr(exact, "PATCH_PATH", tmp_path / "catalog" / "TRADE_COUNT_PATCH.json")
    monkeypatch.setattr(exact, "ROOT", tmp_path)
    monkeypatch.setattr(exact, "_download", lambda *_args, **_kwargs: tmp_path / "verified.gz")

    def scan_and_simulate_collection_update(_path, _row):
        concurrent = {**original, "collection_epoch": 9}
        index_path.write_text(json.dumps(concurrent), encoding="utf-8")
        return {
            "asset_sha256": "a" * 64,
            "trade_count": 2,
            "trade_count_exact": True,
            "unique_trade_count": 2,
            "unique_trade_count_exact": True,
            "unique_identity_method": exact.IDENTITY_VERSION,
        }

    monkeypatch.setattr(exact, "inspect_asset", scan_and_simulate_collection_update)
    before_scan = index_path.read_bytes()
    with pytest.raises(ValueError, match="CANONICAL_INDEX_SOURCE_CHANGED_BEFORE_PUBLISH"):
        exact.backfill(1)

    current = json.loads(index_path.read_text(encoding="utf-8"))
    assert current["collection_epoch"] == 9
    assert current["shards"] == original["shards"]
    assert current["shards"][0].get("trade_count_exact") is False
    assert index_path.read_bytes() != before_scan
