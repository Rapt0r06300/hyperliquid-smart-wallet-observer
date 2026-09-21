from __future__ import annotations

import pytest

from hl_observer.datasets.github_release_bridge import DatasetBridgeError
from hl_observer.datasets.v2_reader import iter_safe_manifests, materialize_safe_shards


def _manifest(status: str, *, verified: bool = True, symbol: str = "BTCUSDT"):
    return {
        "dataset_id": f"{status.lower()}-{symbol.lower()}",
        "quality_status": status,
        "validation_allowed": status == "SAFE",
        "asset_verified": verified,
        "venue": "bybit",
        "family": "l2Book",
        "symbol": symbol,
        "start_ts_ms": 1000,
        "end_ts_ms": 2000,
        "sha256": "a" * 64,
        "release": {
            "repository": "Rapt0r06300/alina-smartflow-datasets-v2",
            "asset_id": 1,
            "asset_name": "x.jsonl.gz",
            "remote_size": 10,
            "remote_digest": "sha256:" + "a" * 64,
        },
    }


def test_reader_exposes_only_safe_verified_overlapping_shards() -> None:
    run = {
        "manifests": [
            _manifest("SAFE"),
            _manifest("PARTIAL", symbol="ETHUSDT"),
            _manifest("REJECT", symbol="SOLUSDT"),
        ]
    }
    rows = list(
        iter_safe_manifests(
            [run],
            venues=["bybit"],
            families=["l2Book"],
            symbols=["BTCUSDT", "ETHUSDT", "SOLUSDT"],
            start_ts_ms=1500,
            end_ts_ms=1600,
        )
    )
    assert [row["symbol"] for row in rows] == ["BTCUSDT"]


def test_materializer_refuses_non_safe_manifest(tmp_path) -> None:
    with pytest.raises(DatasetBridgeError, match="non-SAFE"):
        materialize_safe_shards(
            [_manifest("PARTIAL")],
            tmp_path,
        )
