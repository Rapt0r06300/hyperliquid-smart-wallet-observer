from hl_observer.datasets.replay_coverage import (
    build_safe_coverage_matrix,
    coverage_age_receipt,
    coverage_compression_receipt,
    coverage_contract_receipt,
    coverage_cutoff_receipt,
    coverage_duplicate_receipt,
    coverage_field_type_receipt,
    coverage_finite_receipt,
    coverage_manifest_compatibility_receipt,
    coverage_null_field_receipt,
    coverage_partial_replay_receipt,
    coverage_publication_receipt,
    coverage_reject_validation_receipt,
    coverage_replay_receipt,
    coverage_required_field_receipt,
    coverage_retry_receipt,
    coverage_sha256_receipt,
    coverage_size_receipt,
    coverage_symlink_receipt,
    coverage_unique_counts_receipt,
    coverage_zip_slip_receipt,
    safe_coverage_receipt,
)


def _manifest():
    return [{"quality_status": "SAFE", "validation_allowed": True, "asset_verified": True, "venue": "hyperliquid", "family": "bbo", "symbol": "BTC", "start_ts_ms": 10, "end_ts_ms": 20, "event_count": 2, "bytes": 100, "dataset_id": "d1"}]


def test_hvr_0341_coverage_baseline():
    assert build_safe_coverage_matrix(_manifest())["safe_partitions"] == 1
    assert safe_coverage_receipt(_manifest(), required_start_ts_ms=10, required_end_ts_ms=20)["status"] == "PROVEN"


def test_hvr_0342_required_field():
    assert coverage_required_field_receipt({}, field="dataset_id")["status"] == "REJECTED"


def test_hvr_0343_null_field():
    assert coverage_null_field_receipt({"dataset_id": None}, field="dataset_id")["status"] == "REJECTED"


def test_hvr_0344_field_type():
    assert coverage_field_type_receipt({"count": 1}, field="count", expected_type=int)["status"] == "PROVEN"


def test_hvr_0345_nonfinite():
    assert coverage_finite_receipt(float("nan"))["status"] == "REJECTED"


def test_hvr_0346_cutoff():
    assert coverage_cutoff_receipt(event_ts_ms=10, cutoff_ts_ms=10)["status"] == "PROVEN"


def test_hvr_0347_old_event():
    assert coverage_age_receipt(event_ts_ms=9, oldest_allowed_ts_ms=10)["status"] == "REJECTED"


def test_hvr_0348_duplicate():
    assert coverage_duplicate_receipt(event_ids=["e", "e"])["status"] == "REJECTED"


def test_hvr_0349_retry():
    assert coverage_retry_receipt(attempts=2, max_attempts=3, checkpoint_saved=True)["status"] == "PROVEN"


def test_hvr_0350_replay():
    assert coverage_replay_receipt(outputs=[{"safe": True}, {"safe": True}])["status"] == "PROVEN"


def test_hvr_0351_sha256():
    digest = "a" * 64
    assert coverage_sha256_receipt(actual_sha256=digest, expected_sha256=digest)["status"] == "PROVEN"
    assert coverage_sha256_receipt(actual_sha256="b" * 64, expected_sha256=digest)["status"] == "REJECTED"


def test_hvr_0352_size():
    assert coverage_size_receipt(actual_size=10, expected_size=10)["status"] == "PROVEN"
    assert coverage_size_receipt(actual_size=9, expected_size=10)["status"] == "REJECTED"


def test_hvr_0353_compression():
    assert coverage_compression_receipt(expected_size=10, observed_size=10, complete=True)["status"] == "PROVEN"
    assert coverage_compression_receipt(expected_size=10, observed_size=9, complete=False)["status"] == "REJECTED"


def test_hvr_0354_zip_slip():
    assert coverage_zip_slip_receipt("../outside.json")["status"] == "PROVEN"
    assert coverage_zip_slip_receipt("safe/data.json")["status"] == "REJECTED"


def test_hvr_0355_symlink():
    assert coverage_symlink_receipt(is_symlink=False, within_root=True)["status"] == "PROVEN"
    assert coverage_symlink_receipt(is_symlink=True, within_root=False)["status"] == "REJECTED"


def test_hvr_0356_partial():
    assert coverage_partial_replay_receipt(status="PARTIAL", replayable=False)["status"] == "PROVEN"
    assert coverage_partial_replay_receipt(status="PARTIAL", replayable=True)["status"] == "REJECTED"


def test_hvr_0357_reject():
    assert coverage_reject_validation_receipt(status="REJECT", validated=False)["status"] == "PROVEN"
    assert coverage_reject_validation_receipt(status="REJECT", validated=True)["status"] == "REJECTED"


def test_hvr_0358_unique_counts():
    assert coverage_unique_counts_receipt(total_count=2, unique_count=2, unique_ids=["a", "b"])["status"] == "PROVEN"
    assert coverage_unique_counts_receipt(total_count=2, unique_count=1, unique_ids=["a"])["status"] == "REJECTED"


def test_hvr_0359_manifest():
    assert coverage_manifest_compatibility_receipt(manifest_version="v1", required_version="v1", compatible=True)["status"] == "PROVEN"
    assert coverage_manifest_compatibility_receipt(manifest_version="v1", required_version="v2", compatible=False)["status"] == "REJECTED"


def test_hvr_0360_publication():
    assert coverage_publication_receipt(status="COMPLETE", manifest_committed=True, receipt_written=True)["status"] == "PROVEN"
    assert coverage_publication_receipt(status="PARTIAL", manifest_committed=False, receipt_written=False)["status"] == "REJECTED"


def test_coverage_contract_positive():
    row = {"quality_status": "SAFE", "validation_allowed": True, "asset_verified": True, "dataset_id": "d1", "symbol": "BTC", "start_ts_ms": 10, "end_ts_ms": 20, "event_count": 2}
    assert coverage_contract_receipt(row)["status"] == "PROVEN"
