from __future__ import annotations

import json
from pathlib import Path

from hl_observer.simulation.economic_freeze_registry import (
    first_compatible_freeze,
    first_freeze,
    list_freezes,
    parameter_hash,
    reuse_or_create_freeze,
    split_pre_post_freeze,
)


def _write(root: Path, family: str, name: str, ts: int, params: dict) -> None:
    target = root / "runtime" / "reports" / "economic_campaigns" / "freezes" / family / name
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        json.dumps(
            {
                "schema_version": "hypersmart.economic_parameter_freeze.v1",
                "campaign_id": name.removesuffix(".json"),
                "family": family,
                "frozen_at_ms": ts,
                "selected_before_final_evaluation": True,
                "parameters": params,
                "parameters_sha256": parameter_hash(params),
                "dataset_provenance": {},
                "path": target.relative_to(root).as_posix(),
            }
        ),
        encoding="utf-8",
    )


def test_registry_reuses_earliest_compatible_freeze(tmp_path: Path):
    params = {"horizon_ms": 1000, "seuil": 8.0}
    _write(tmp_path, "lead_lag", "later.json", 2_000, params)
    _write(tmp_path, "lead_lag", "first.json", 1_000, params)
    _write(tmp_path, "lead_lag", "other.json", 500, {"horizon_ms": 500, "seuil": 8.0})

    rows = list_freezes(tmp_path, "lead_lag")
    assert [row["frozen_at_ms"] for row in rows] == [500, 1000, 2000]
    assert first_freeze(tmp_path, "lead_lag")["frozen_at_ms"] == 500
    assert first_compatible_freeze(tmp_path, "lead_lag", params)["frozen_at_ms"] == 1000


def test_reuse_or_create_keeps_original_boundary_when_dataset_grows(tmp_path: Path):
    params = {"horizon_ms": 1000, "seuil": 8.0}
    first = reuse_or_create_freeze(
        tmp_path,
        "lead_lag",
        params,
        {"dataset_fingerprint": "a" * 64, "files": [{"path": "first"}]},
    )
    second = reuse_or_create_freeze(
        tmp_path,
        "lead_lag",
        params,
        {"dataset_fingerprint": "b" * 64, "files": [{"path": "grown"}]},
    )

    assert second["campaign_id"] == first["campaign_id"]
    assert second["frozen_at_ms"] == first["frozen_at_ms"]
    assert second["dataset_provenance"] == first["dataset_provenance"]
    assert len(list_freezes(tmp_path, "lead_lag")) == 1


def test_reuse_or_create_makes_new_boundary_when_parameters_change(tmp_path: Path):
    first = reuse_or_create_freeze(
        tmp_path,
        "lead_lag",
        {"horizon_ms": 1000},
        {"dataset_fingerprint": "a" * 64, "files": []},
    )
    second = reuse_or_create_freeze(
        tmp_path,
        "lead_lag",
        {"horizon_ms": 1500},
        {"dataset_fingerprint": "b" * 64, "files": []},
    )

    assert second["parameters_sha256"] != first["parameters_sha256"]
    assert len(list_freezes(tmp_path, "lead_lag")) == 2


def test_corrupt_freeze_is_never_reused(tmp_path: Path):
    params = {"horizon_ms": 1000}
    _write(tmp_path, "lead_lag", "bad.json", 1000, params)
    path = next((tmp_path / "runtime/reports/economic_campaigns/freezes/lead_lag").glob("*.json"))
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["parameters"]["horizon_ms"] = 999
    path.write_text(json.dumps(payload), encoding="utf-8")
    assert list_freezes(tmp_path, "lead_lag") == []


def test_physical_forward_requires_strictly_post_freeze_timestamp():
    freeze = {"frozen_at_ms": 1_000}
    pre, post = split_pre_post_freeze(
        [{"ts_ms": 999}, {"ts_ms": 1000}, {"ts_ms": 1001}, {"ts_ms": 2000}],
        freeze,
    )
    assert [row["ts_ms"] for row in pre] == [999, 1000]
    assert [row["ts_ms"] for row in post] == [1001, 2000]
