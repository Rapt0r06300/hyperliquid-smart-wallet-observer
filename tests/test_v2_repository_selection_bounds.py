from __future__ import annotations

from hl_observer.datasets.v2_repository import select_safe_shards


def _row(dataset_id: str, start: int, end: int) -> dict:
    return {
        "dataset_id": dataset_id,
        "family": "trades",
        "venue": "binance",
        "symbol": "BTCUSDT",
        "start_ts_ms": start,
        "end_ts_ms": end,
        "sha256": "a" * 64,
        "bytes": 100,
        "event_count": 10,
        "release_repository": "Rapt0r06300/alina-smartflow-datasets-v2",
        "release_tag": "tag",
        "release_asset": dataset_id + ".jsonl.gz",
        "manifest_path": "datasets/safe/" + dataset_id + ".manifest.json",
        "quality_status": "SAFE",
        "replay_compatible": True,
    }


def test_frozen_end_cutoff_rejects_shard_crossing_into_future() -> None:
    index = {
        "shards": [
            _row("contained", 100, 199),
            _row("crosses-cutoff", 150, 250),
            _row("future", 251, 300),
        ]
    }

    selected = select_safe_shards(index, end_ts_ms=200)

    assert [row.dataset_id for row in selected] == ["contained"]


def test_frozen_start_boundary_rejects_shard_beginning_before_window() -> None:
    index = {
        "shards": [
            _row("past-overlap", 50, 120),
            _row("contained", 100, 180),
        ]
    }

    selected = select_safe_shards(index, start_ts_ms=100, end_ts_ms=200)

    assert [row.dataset_id for row in selected] == ["contained"]
