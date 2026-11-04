from hl_observer.datasets.dataset_untrusted_guard import (
    dataset_age_receipt,
    dataset_compression_receipt,
    dataset_contract_receipt,
    dataset_cutoff_receipt,
    dataset_duplicate_receipt,
    dataset_field_type_receipt,
    dataset_finite_receipt,
    dataset_manifest_compatibility_receipt,
    dataset_null_field_receipt,
    dataset_partial_replay_receipt,
    dataset_publication_receipt,
    dataset_reject_validation_receipt,
    dataset_replay_receipt,
    dataset_required_field_receipt,
    dataset_retry_receipt,
    dataset_sha256_receipt,
    dataset_size_receipt,
    dataset_symlink_receipt,
    dataset_unique_counts_receipt,
    dataset_zip_slip_receipt,
    untrusted_provenance_receipt,
)


def test_hvr_0301_untrusted_baseline(tmp_path):
    assert untrusted_provenance_receipt(tmp_path)["status"] == "PROVEN"


def test_hvr_0302_required_field():
    assert dataset_required_field_receipt({}, field="dataset_id")["status"] == "REJECTED"


def test_hvr_0303_null_field():
    assert dataset_null_field_receipt({"dataset_id": None}, field="dataset_id")["status"] == "REJECTED"


def test_hvr_0304_field_type():
    assert dataset_field_type_receipt({"count": 1}, field="count", expected_type=int)["status"] == "PROVEN"
    assert dataset_field_type_receipt({"count": "1"}, field="count", expected_type=int)["status"] == "REJECTED"


def test_hvr_0305_nonfinite():
    assert dataset_finite_receipt(float("nan"))["status"] == "REJECTED"


def test_hvr_0306_cutoff():
    assert dataset_cutoff_receipt(event_ts_ms=10, cutoff_ts_ms=10)["status"] == "PROVEN"


def test_hvr_0307_old_event():
    assert dataset_age_receipt(event_ts_ms=9, oldest_allowed_ts_ms=10)["status"] == "REJECTED"


def test_hvr_0308_duplicate():
    assert dataset_duplicate_receipt(event_ids=["e", "e"])["status"] == "REJECTED"


def test_hvr_0309_retry():
    assert dataset_retry_receipt(attempts=2, max_attempts=3, checkpoint_saved=True)["status"] == "PROVEN"


def test_hvr_0310_replay():
    assert dataset_replay_receipt(outputs=[{"safe": True}, {"safe": True}])["status"] == "PROVEN"


def test_hvr_0311_sha256():
    digest = "a" * 64
    assert dataset_sha256_receipt(actual_sha256=digest, expected_sha256=digest)["status"] == "PROVEN"
    assert dataset_sha256_receipt(actual_sha256="b" * 64, expected_sha256=digest)["status"] == "REJECTED"


def test_hvr_0312_size():
    assert dataset_size_receipt(actual_size=10, expected_size=10)["status"] == "PROVEN"
    assert dataset_size_receipt(actual_size=9, expected_size=10)["status"] == "REJECTED"


def test_hvr_0313_compression():
    assert dataset_compression_receipt(expected_size=10, observed_size=10, complete=True)["status"] == "PROVEN"
    assert dataset_compression_receipt(expected_size=10, observed_size=9, complete=False)["status"] == "REJECTED"


def test_hvr_0314_zip_slip():
    assert dataset_zip_slip_receipt("../outside.json")["status"] == "PROVEN"
    assert dataset_zip_slip_receipt("safe/data.json")["status"] == "REJECTED"


def test_hvr_0315_symlink():
    assert dataset_symlink_receipt(is_symlink=False, within_root=True)["status"] == "PROVEN"
    assert dataset_symlink_receipt(is_symlink=True, within_root=False)["status"] == "REJECTED"


def test_hvr_0316_partial_not_replayable():
    assert dataset_partial_replay_receipt(status="PARTIAL", replayable=False)["status"] == "PROVEN"
    assert dataset_partial_replay_receipt(status="PARTIAL", replayable=True)["status"] == "REJECTED"


def test_hvr_0317_reject_not_validated():
    assert dataset_reject_validation_receipt(status="REJECT", validated=False)["status"] == "PROVEN"
    assert dataset_reject_validation_receipt(status="REJECT", validated=True)["status"] == "REJECTED"


def test_hvr_0318_unique_counts():
    assert dataset_unique_counts_receipt(total_count=2, unique_count=2, unique_ids=["a", "b"])["status"] == "PROVEN"
    assert dataset_unique_counts_receipt(total_count=2, unique_count=1, unique_ids=["a"])["status"] == "REJECTED"


def test_hvr_0319_manifest_compatibility():
    assert dataset_manifest_compatibility_receipt(manifest_version="v1", required_version="v1", compatible=True)["status"] == "PROVEN"
    assert dataset_manifest_compatibility_receipt(manifest_version="v1", required_version="v2", compatible=False)["status"] == "REJECTED"


def test_hvr_0320_publication():
    assert dataset_publication_receipt(status="COMPLETE", manifest_committed=True, receipt_written=True)["status"] == "PROVEN"
    assert dataset_publication_receipt(status="PARTIAL", manifest_committed=False, receipt_written=False)["status"] == "REJECTED"


def test_dataset_contract_positive():
    manifest = {"dataset_id": "safe-1", "status": "SAFE", "manifest_sha256": "a" * 64, "replay_compatible": True, "publication_complete": True}
    assert dataset_contract_receipt(manifest)["status"] == "PROVEN"
