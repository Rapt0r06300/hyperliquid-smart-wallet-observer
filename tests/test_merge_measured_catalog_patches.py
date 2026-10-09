from __future__ import annotations

import json

import pytest

from tools.merge_measured_catalog_patches import merge_patch, merge_directory


def row(sha="a" * 64):
    return {"dataset_id": "example", "sha256": sha}


def record(sha="a" * 64, count=3):
    return {
        "asset_sha256": sha,
        "exact": True,
        "record_count": count,
        "valid_record_count": count,
        "invalid_record_count": 0,
        "unique_record_count": count,
    }


def test_verified_old_evidence_survives_a_newer_retryable_error():
    current = {"records": {"example": record()}}
    measured = {"records": {"example": {"status": "UNAVAILABLE", "retryable": True}}}
    out = merge_patch(current, measured, index_rows=[row()],
                      kind="records", schema="alina.record_count_patch.v1")
    assert out["records"]["example"]["record_count"] == 3
    assert out["remaining_assets"] == 0
    assert out["coverage_complete"] is True


def test_exact_measured_new_evidence_wins_unproven_old_status():
    current = {"records": {"example": {"retryable": True, "status": "UNAVAILABLE"}}}
    measured = {"records": {"example": record()}}
    out = merge_patch(current, measured, index_rows=[row()],
                      kind="records", schema="alina.record_count_patch.v1")
    assert out["exact_assets"] == 1
    assert out["records"]["example"]["record_count"] == 3


def test_changed_sha_does_not_reuse_stale_evidence():
    current = {"records": {"example": record()}}
    measured = {"records": {"example": record()}}
    out = merge_patch(current, measured, index_rows=[row("b" * 64)],
                      kind="records", schema="alina.record_count_patch.v1")
    assert out["coverage_complete"] is False
    assert out["remaining_assets"] == 1
    assert "example" not in out["records"]


def test_conflicting_exact_record_counts_fail_closed():
    with pytest.raises(ValueError, match="conflicting exact"):
        merge_patch(
            {"records": {"example": record(count=3)}},
            {"records": {"example": record(count=4)}},
            index_rows=[row()],
            kind="records", schema="alina.record_count_patch.v1",
        )


def test_merge_directory_updates_both_without_losing_new_main_data(tmp_path):
    repo = tmp_path / "repo"
    measurements = tmp_path / "measurements"
    (repo / "catalog").mkdir(parents=True)
    measurements.mkdir()
    (repo / "catalog" / "DATA_INDEX.json").write_text(json.dumps({"shards": [row()]}))
    for file_name, key, val in (
        ("UNCOMPRESSED_SIZE_PATCH.json", "sizes", {"uncompressed_bytes": 200, "asset_sha256": "a" * 64}),
        ("RECORD_COUNT_PATCH.json", "records", record()),
    ):
        (repo / "catalog" / file_name).write_text(json.dumps({key: {"example": val}}))
        (measurements / file_name).write_text(json.dumps({key: {"example": {"retryable": True}}}))
    result = merge_directory(measurements, repo)
    assert result["sizes"]["exact"] == 1
    assert result["records"]["exact"] == 1
    assert result["records"]["remaining"] == 0
