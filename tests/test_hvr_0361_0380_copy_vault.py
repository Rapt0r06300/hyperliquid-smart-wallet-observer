from pathlib import Path

from hl_observer.datasets.github_release_bridge import DatasetRecord
from hl_observer.datasets.streaming_materializer import (
    materialization_age_receipt,
    materialization_compression_receipt,
    materialization_cutoff_receipt,
    materialization_duplicate_receipt,
    materialization_field_type_receipt,
    materialization_finite_receipt,
    materialization_manifest_compatibility_receipt,
    materialization_null_field_receipt,
    materialization_partial_replay_receipt,
    materialization_publication_receipt,
    materialization_reject_validation_receipt,
    materialization_replay_receipt,
    materialization_required_field_receipt,
    materialization_retry_receipt,
    materialization_safety_receipt,
    materialization_sha256_receipt,
    materialization_size_receipt,
    materialization_symlink_receipt,
    materialization_unique_counts_receipt,
    materialization_zip_slip_receipt,
)


def test_hvr_0361_materialization_baseline_is_safe():
    rows = [
        DatasetRecord(
            relative_path="safe/file.bin",
            size=1,
            sha256="a" * 64,
            storage="raw_chunks",
            chunks=({"asset": "a", "part": 1},),
        )
    ]
    assert materialization_safety_receipt(Path("."), rows)["status"] == "PROVEN"


def test_hvr_0362_required_field():
    assert materialization_required_field_receipt({"sha256": "a"}, field="sha256")["status"] == "PROVEN"
    assert materialization_required_field_receipt({}, field="sha256")["status"] == "REJECTED"


def test_hvr_0363_null_field():
    assert materialization_null_field_receipt({"sha256": "a"}, field="sha256")["status"] == "PROVEN"
    assert materialization_null_field_receipt({"sha256": None}, field="sha256")["status"] == "REJECTED"


def test_hvr_0364_field_type():
    assert materialization_field_type_receipt({"size": 1}, field="size", expected_type=int)["status"] == "PROVEN"
    assert materialization_field_type_receipt({"size": "1"}, field="size", expected_type=int)["status"] == "REJECTED"


def test_hvr_0365_finite_value():
    assert materialization_finite_receipt(1.5)["status"] == "PROVEN"
    assert materialization_finite_receipt(float("nan"))["status"] == "REJECTED"


def test_hvr_0366_cutoff():
    assert materialization_cutoff_receipt(event_ts_ms=10, cutoff_ts_ms=10)["status"] == "PROVEN"
    assert materialization_cutoff_receipt(event_ts_ms=11, cutoff_ts_ms=10)["status"] == "REJECTED"


def test_hvr_0367_age():
    assert materialization_age_receipt(event_ts_ms=10, oldest_allowed_ts_ms=10)["status"] == "PROVEN"
    assert materialization_age_receipt(event_ts_ms=9, oldest_allowed_ts_ms=10)["status"] == "REJECTED"


def test_hvr_0368_duplicate_events():
    assert materialization_duplicate_receipt(event_ids=["a", "b"])["status"] == "PROVEN"
    assert materialization_duplicate_receipt(event_ids=["a", "a"])["status"] == "REJECTED"


def test_hvr_0369_bounded_retry_requires_checkpoint():
    assert materialization_retry_receipt(attempts=2, max_attempts=3, checkpoint_saved=True)["status"] == "PROVEN"
    assert materialization_retry_receipt(attempts=4, max_attempts=3, checkpoint_saved=True)["status"] == "REJECTED"


def test_hvr_0370_replay_is_deterministic():
    assert materialization_replay_receipt(outputs=[{"count": 1}, {"count": 1}])["status"] == "PROVEN"
    assert materialization_replay_receipt(outputs=[{"count": 1}, {"count": 2}])["status"] == "REJECTED"


def test_hvr_0371_sha256_matches():
    digest = "a" * 64
    assert materialization_sha256_receipt(actual_sha256=digest, expected_sha256=digest)["status"] == "PROVEN"
    assert materialization_sha256_receipt(actual_sha256="b" * 64, expected_sha256=digest)["status"] == "REJECTED"


def test_hvr_0372_size_matches():
    assert materialization_size_receipt(actual_size=10, expected_size=10)["status"] == "PROVEN"
    assert materialization_size_receipt(actual_size=9, expected_size=10)["status"] == "REJECTED"


def test_hvr_0373_compression_is_complete():
    assert materialization_compression_receipt(expected_size=10, observed_size=10, complete=True)["status"] == "PROVEN"
    assert materialization_compression_receipt(expected_size=10, observed_size=9, complete=False)["status"] == "REJECTED"


def test_hvr_0374_zip_slip_is_refused():
    assert materialization_zip_slip_receipt("../outside.json")["status"] == "PROVEN"
    assert materialization_zip_slip_receipt("safe/data.json")["status"] == "REJECTED"


def test_hvr_0375_symlink_is_refused():
    assert materialization_symlink_receipt(is_symlink=False, within_root=True)["status"] == "PROVEN"
    assert materialization_symlink_receipt(is_symlink=True, within_root=False)["status"] == "REJECTED"


def test_hvr_0376_partial_replay_is_not_promoted():
    assert materialization_partial_replay_receipt(status="PARTIAL", replayable=False)["status"] == "PROVEN"
    assert materialization_partial_replay_receipt(status="PARTIAL", replayable=True)["status"] == "REJECTED"


def test_hvr_0377_reject_is_not_validated():
    assert materialization_reject_validation_receipt(status="REJECT", validated=False)["status"] == "PROVEN"
    assert materialization_reject_validation_receipt(status="REJECT", validated=True)["status"] == "REJECTED"


def test_hvr_0378_unique_counts_match():
    assert materialization_unique_counts_receipt(total_count=2, unique_count=2, unique_ids=["a", "b"])["status"] == "PROVEN"
    assert materialization_unique_counts_receipt(total_count=2, unique_count=1, unique_ids=["a"])["status"] == "REJECTED"


def test_hvr_0379_manifest_is_compatible():
    assert materialization_manifest_compatibility_receipt(manifest_version="v1", required_version="v1", compatible=True)["status"] == "PROVEN"
    assert materialization_manifest_compatibility_receipt(manifest_version="v1", required_version="v2", compatible=False)["status"] == "REJECTED"


def test_hvr_0380_publication_requires_manifest_and_receipt():
    assert materialization_publication_receipt(status="COMPLETE", manifest_committed=True, receipt_written=True)["status"] == "PROVEN"
    assert materialization_publication_receipt(status="PARTIAL", manifest_committed=False, receipt_written=False)["status"] == "REJECTED"
