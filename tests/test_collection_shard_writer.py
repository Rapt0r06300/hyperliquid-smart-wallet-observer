from __future__ import annotations

import gzip
import json

import pytest

from hl_observer.collection.shard_writer import ImmutableGzipShardWriter


def test_shard_is_compressed_hashed_and_manifested(tmp_path) -> None:
    path = tmp_path / "btc-l2.jsonl.gz"
    writer = ImmutableGzipShardWriter(
        path,
        venue="bybit",
        family="l2",
        symbol="BTCUSDT",
        collector_version="test",
    )
    writer.append({"exchange_ts_ms": 1_000, "receive_ts_ms": 1_010, "bid": 100})
    writer.append({"exchange_ts_ms": 1_020, "receive_ts_ms": 1_030, "bid": 101})
    manifest = writer.close()

    assert manifest.event_count == 2
    assert len(manifest.sha256) == 64
    assert manifest.bytes > 0
    with gzip.open(path, "rt", encoding="utf-8") as handle:
        rows = [json.loads(line) for line in handle]
    assert len(rows) == 2


def test_shard_refuses_missing_timestamps(tmp_path) -> None:
    writer = ImmutableGzipShardWriter(
        tmp_path / "bad.jsonl.gz",
        venue="okx",
        family="l2",
        symbol="BTC-USDT-SWAP",
        collector_version="test",
    )
    with pytest.raises(ValueError):
        writer.append({"receive_ts_ms": 1_000})
