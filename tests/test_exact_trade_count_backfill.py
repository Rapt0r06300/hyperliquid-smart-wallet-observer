from __future__ import annotations

import gzip
import hashlib
import json

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
