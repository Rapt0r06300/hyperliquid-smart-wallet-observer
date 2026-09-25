from __future__ import annotations

import json

from hl_observer.datasets.v2_repository import SafeShard
from hl_observer.ops import v2_dataset_bridge


def _shard(dataset_id: str, start: int) -> SafeShard:
    return SafeShard(
        dataset_id=dataset_id,
        family="bbo",
        venue="hyperliquid",
        symbol="BTC",
        start_ts_ms=start,
        end_ts_ms=start + 10,
        sha256="a" * 64,
        bytes=100,
        event_count=10,
        release_repository="Rapt0r06300/alina-smartflow-datasets-v2",
        release_tag="data-v2-test",
        release_asset=f"{dataset_id}.jsonl.gz",
        manifest_path=f"datasets/safe/{dataset_id}.manifest.json",
    )


def test_bridge_max_shards_keeps_newest(monkeypatch, capsys, tmp_path):
    index={"schema":"alina.data_index.v2","shards":[]}
    monkeypatch.setattr(v2_dataset_bridge, "load_index", lambda: (index, "digest"))
    monkeypatch.setattr(
        v2_dataset_bridge,
        "select_safe_shards",
        lambda *args, **kwargs: [_shard("old", 1), _shard("mid", 2), _shard("new", 3)],
    )
    rc=v2_dataset_bridge.main([
        "plan",
        "--output", str(tmp_path),
        "--max-shards", "2",
    ])
    assert rc == 0
    payload=json.loads(capsys.readouterr().out)
    assert payload["safe_shards"] == 2
    assert payload["dataset_ids"] == ["mid", "new"]


def test_bridge_materialize_refuses_empty_selection(monkeypatch, capsys, tmp_path):
    monkeypatch.setattr(
        v2_dataset_bridge,
        "load_index",
        lambda: ({"schema":"alina.data_index.v2","shards":[]}, "digest"),
    )
    monkeypatch.setattr(v2_dataset_bridge, "select_safe_shards", lambda *a, **k: [])
    rc=v2_dataset_bridge.main(["materialize","--output",str(tmp_path),"--max-shards","1"])
    assert rc == 2
    assert "DATASET_V2_NO_GO" in capsys.readouterr().out
