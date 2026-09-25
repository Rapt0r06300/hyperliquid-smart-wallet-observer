from __future__ import annotations

from pathlib import Path

import pytest

from hl_observer.datasets.v2_repository import (
    DatasetV2Error,
    SafeShard,
    select_safe_shards,
)


def _safe_row(**overrides):
    row = {
        "dataset_id": "x",
        "family": "l2Book",
        "venue": "bybit",
        "symbol": "BTCUSDT",
        "start_ts_ms": 100,
        "end_ts_ms": 200,
        "sha256": "a" * 64,
        "bytes": 123,
        "event_count": 10,
        "quality_status": "SAFE",
        "replay_compatible": True,
        "release_repository": "Rapt0r06300/alina-smartflow-datasets-v2",
        "release_tag": "v2-test",
        "release_asset": "x.jsonl.gz",
        "manifest_path": "datasets/safe/x.manifest.json",
    }
    row.update(overrides)
    return row


def test_selector_only_exposes_safe_rows() -> None:
    index = {
        "schema": "alina.data_index.v2",
        "shards": [
            _safe_row(),
            _safe_row(dataset_id="partial", quality_status="PARTIAL"),
            _safe_row(dataset_id="wrong-symbol", symbol="ETHUSDT"),
        ],
    }
    rows = select_safe_shards(index, symbols=["BTCUSDT"])
    assert [row.dataset_id for row in rows] == ["x"]


def test_safe_row_requires_exact_release_locator() -> None:
    with pytest.raises(DatasetV2Error):
        SafeShard.from_index_row(_safe_row(release_tag=""))


def test_foreign_release_repository_is_refused() -> None:
    with pytest.raises(DatasetV2Error):
        SafeShard.from_index_row(
            _safe_row(release_repository="someone/another-dataset")
        )


def test_time_window_uses_overlap_not_filename_guessing() -> None:
    index = {
        "shards": [
            _safe_row(dataset_id="old", start_ts_ms=0, end_ts_ms=99),
            _safe_row(dataset_id="hit", start_ts_ms=100, end_ts_ms=200),
            _safe_row(dataset_id="new", start_ts_ms=201, end_ts_ms=300),
        ]
    }
    rows = select_safe_shards(index, start_ts_ms=150, end_ts_ms=250)
    assert [row.dataset_id for row in rows] == ["hit", "new"]


def test_selector_refuses_safe_without_replay_compatibility() -> None:
    index={"shards":[_safe_row(dataset_id="no-replay", replay_compatible=False)]}
    assert select_safe_shards(index) == []
