from hl_observer.datasets.v2_pipeline import (
    pipeline_age_receipt,
    pipeline_compression_receipt,
    pipeline_cutoff_receipt,
    pipeline_duplicate_receipt,
    pipeline_field_type_receipt,
    pipeline_finite_receipt,
    pipeline_manifest_compatibility_receipt,
    pipeline_null_field_receipt,
    pipeline_partial_replay_receipt,
    pipeline_publication_receipt,
    pipeline_reject_validation_receipt,
    pipeline_replay_receipt,
    pipeline_required_field_receipt,
    pipeline_retry_receipt,
    pipeline_safety_receipt,
    pipeline_sha256_receipt,
    pipeline_size_receipt,
    pipeline_symlink_receipt,
    pipeline_unique_counts_receipt,
    pipeline_zip_slip_receipt,
)


def _safe_manifest() -> dict[str, object]:
    return {
        "family": "copy_vault_fills",
        "event_count": 2,
        "bytes": 100,
        "sha256": "a" * 64,
        "collector_version": "collector-1",
        "start_ts_ms": 10,
        "end_ts_ms": 20,
        "integrity": {
            "gap_count": 0,
            "regression_count": 0,
            "desync_count": 0,
            "duplicate_count": 0,
            "missing_timestamp_count": 0,
            "missing_monotonic_count": 0,
        },
        "provenance": {
            "public_data_only": True,
            "authenticated": False,
            "real_execution": False,
            "transports": ["https"],
        },
        "reconciliation": {"status": "MATCHED"},
        "required_channels": [],
        "observed_channels": [],
        "asset_verified": True,
        "replay_compatible": True,
    }


def test_hvr_0381_pipeline_baseline_is_safe():
    result = pipeline_safety_receipt(_safe_manifest())
    assert result["status"] == "PROVEN"
    assert result["quality_status"] == "SAFE"


def test_hvr_0382_required_field():
    assert pipeline_required_field_receipt({"sha256": "a"}, field="sha256")["status"] == "PROVEN"
    assert pipeline_required_field_receipt({}, field="sha256")["status"] == "REJECTED"


def test_hvr_0383_null_field():
    assert pipeline_null_field_receipt({"sha256": "a"}, field="sha256")["status"] == "PROVEN"
    assert pipeline_null_field_receipt({"sha256": None}, field="sha256")["status"] == "REJECTED"


def test_hvr_0384_field_type():
    assert pipeline_field_type_receipt({"size": 1}, field="size", expected_type=int)["status"] == "PROVEN"
    assert pipeline_field_type_receipt({"size": "1"}, field="size", expected_type=int)["status"] == "REJECTED"


def test_hvr_0385_finite_value():
    assert pipeline_finite_receipt(1.5)["status"] == "PROVEN"
    assert pipeline_finite_receipt(float("nan"))["status"] == "REJECTED"


def test_hvr_0386_cutoff():
    assert pipeline_cutoff_receipt(event_ts_ms=10, cutoff_ts_ms=10)["status"] == "PROVEN"
    assert pipeline_cutoff_receipt(event_ts_ms=11, cutoff_ts_ms=10)["status"] == "REJECTED"


def test_hvr_0387_age():
    assert pipeline_age_receipt(event_ts_ms=10, oldest_allowed_ts_ms=10)["status"] == "PROVEN"
    assert pipeline_age_receipt(event_ts_ms=9, oldest_allowed_ts_ms=10)["status"] == "REJECTED"


def test_hvr_0388_duplicate_events():
    assert pipeline_duplicate_receipt(event_ids=["a", "b"])["status"] == "PROVEN"
    assert pipeline_duplicate_receipt(event_ids=["a", "a"])["status"] == "REJECTED"


def test_hvr_0389_bounded_retry_requires_checkpoint():
    assert pipeline_retry_receipt(attempts=2, max_attempts=3, checkpoint_saved=True)["status"] == "PROVEN"
    assert pipeline_retry_receipt(attempts=4, max_attempts=3, checkpoint_saved=True)["status"] == "REJECTED"


def test_hvr_0390_replay_is_deterministic():
    assert pipeline_replay_receipt(outputs=[{"count": 1}, {"count": 1}])["status"] == "PROVEN"
    assert pipeline_replay_receipt(outputs=[{"count": 1}, {"count": 2}])["status"] == "REJECTED"


def test_hvr_0391_sha256_matches():
    digest = "a" * 64
    assert pipeline_sha256_receipt(actual_sha256=digest, expected_sha256=digest)["status"] == "PROVEN"
    assert pipeline_sha256_receipt(actual_sha256="b" * 64, expected_sha256=digest)["status"] == "REJECTED"


def test_hvr_0392_size_matches():
    assert pipeline_size_receipt(actual_size=10, expected_size=10)["status"] == "PROVEN"
    assert pipeline_size_receipt(actual_size=9, expected_size=10)["status"] == "REJECTED"


def test_hvr_0393_compression_is_complete():
    assert pipeline_compression_receipt(expected_size=10, observed_size=10, complete=True)["status"] == "PROVEN"
    assert pipeline_compression_receipt(expected_size=10, observed_size=9, complete=False)["status"] == "REJECTED"


def test_hvr_0394_zip_slip_is_refused():
    assert pipeline_zip_slip_receipt("../outside.json")["status"] == "PROVEN"
    assert pipeline_zip_slip_receipt("safe/data.json")["status"] == "REJECTED"


def test_hvr_0395_symlink_is_refused():
    assert pipeline_symlink_receipt(is_symlink=False, within_root=True)["status"] == "PROVEN"
    assert pipeline_symlink_receipt(is_symlink=True, within_root=False)["status"] == "REJECTED"


def test_hvr_0396_partial_replay_is_not_promoted():
    assert pipeline_partial_replay_receipt(status="PARTIAL", replayable=False)["status"] == "PROVEN"
    assert pipeline_partial_replay_receipt(status="PARTIAL", replayable=True)["status"] == "REJECTED"


def test_hvr_0397_reject_is_not_validated():
    assert pipeline_reject_validation_receipt(status="REJECT", validated=False)["status"] == "PROVEN"
    assert pipeline_reject_validation_receipt(status="REJECT", validated=True)["status"] == "REJECTED"


def test_hvr_0398_unique_counts_match():
    assert pipeline_unique_counts_receipt(total_count=2, unique_count=2, unique_ids=["a", "b"])["status"] == "PROVEN"
    assert pipeline_unique_counts_receipt(total_count=2, unique_count=1, unique_ids=["a"])["status"] == "REJECTED"


def test_hvr_0399_manifest_is_compatible():
    assert pipeline_manifest_compatibility_receipt(manifest_version="v1", required_version="v1", compatible=True)["status"] == "PROVEN"
    assert pipeline_manifest_compatibility_receipt(manifest_version="v1", required_version="v2", compatible=False)["status"] == "REJECTED"


def test_hvr_0400_publication_requires_manifest_and_receipt():
    assert pipeline_publication_receipt(status="COMPLETE", manifest_committed=True, receipt_written=True)["status"] == "PROVEN"
    assert pipeline_publication_receipt(status="PARTIAL", manifest_committed=False, receipt_written=False)["status"] == "REJECTED"
