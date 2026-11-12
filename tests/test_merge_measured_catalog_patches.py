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


@pytest.mark.parametrize("variant", ["unique", "valid_invalid"])
def test_same_total_with_different_exact_record_components_fails_closed(variant):
    original = record()
    conflicting = record()
    if variant == "unique":
        conflicting["unique_record_count"] = 2
    else:
        conflicting["valid_record_count"] = 2
        conflicting["invalid_record_count"] = 1
        conflicting["unique_record_count"] = 2
    with pytest.raises(ValueError, match="conflicting exact"):
        merge_patch(
            {"records": {"example": original}},
            {"records": {"example": conflicting}},
            index_rows=[row()], kind="records",
            schema="alina.record_count_patch.v1",
        )


def test_negative_record_component_is_never_certified_exact():
    bad = record()
    bad.update(valid_record_count=-1, invalid_record_count=4,
               unique_record_count=0)
    merged = merge_patch(
        {}, {"records": {"example": bad}},
        index_rows=[row()], kind="records",
        schema="alina.record_count_patch.v1",
    )
    assert merged["exact_assets"] == 0
    assert not merged["coverage_complete"]


def test_oversize_measurement_tables_are_partitioned_without_loss(tmp_path, monkeypatch):
    from tools import measured_catalog_patches as storage
    from tools.measured_catalog_patches import load_patch

    root, measured = tmp_path / "repo", tmp_path / "measured"
    (root / "catalog").mkdir(parents=True)
    measured.mkdir()
    (root / "catalog" / "DATA_INDEX.json").write_text(
        json.dumps({"shards": [row()]}), encoding="utf-8"
    )
    size_value = {"asset_sha256": "a" * 64, "uncompressed_bytes": 200}
    record_value = record()
    for filename, kind, evidence in (
        ("UNCOMPRESSED_SIZE_PATCH.json", "sizes", size_value),
        ("RECORD_COUNT_PATCH.json", "records", record_value),
    ):
        (root / "catalog" / filename).write_text(
            json.dumps({kind: {"example": evidence}}), encoding="utf-8"
        )
        (measured / filename).write_text(
            json.dumps({kind: {"example": {"retryable": True}}}),
            encoding="utf-8",
        )

    monkeypatch.setattr(storage, "MAX_INLINE_BYTES", 1)
    from tools.merge_measured_catalog_patches import merge_directory

    result = merge_directory(measured, root)
    assert result["sizes"]["exact"] == 1
    assert result["records"]["exact"] == 1
    assert load_patch(root / "catalog" / "UNCOMPRESSED_SIZE_PATCH.json", "sizes")["sizes"]["example"] == size_value
    assert load_patch(root / "catalog" / "RECORD_COUNT_PATCH.json", "records")["records"]["example"] == record_value
    assert json.loads(
        (root / "catalog" / "RECORD_COUNT_PATCH.json").read_text()
    )["schema"] == "alina.measured_patch_partitioned.v1"

