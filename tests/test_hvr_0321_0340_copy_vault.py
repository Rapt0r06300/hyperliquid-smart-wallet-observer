from hl_observer.datasets.strategy_data_contracts import (
    evaluate_copy_vault_replay_readiness,
    strategy_age_receipt,
    strategy_compression_receipt,
    strategy_cutoff_receipt,
    strategy_duplicate_receipt,
    strategy_field_type_receipt,
    strategy_finite_receipt,
    strategy_manifest_compatibility_receipt,
    strategy_null_field_receipt,
    strategy_partial_replay_receipt,
    strategy_publication_receipt,
    strategy_reject_validation_receipt,
    strategy_replay_receipt,
    strategy_required_field_receipt,
    strategy_retry_receipt,
    strategy_sha256_receipt,
    strategy_size_receipt,
    strategy_symlink_receipt,
    strategy_unique_counts_receipt,
    strategy_zip_slip_receipt,
    strategy_done_receipt,
)


def test_hvr_0321_replay_readiness_baseline():
    manifests = [{"venue": "hyperliquid", "family": family, "collection_run_id": "r1"} for family in ("userFills", "bbo", "l2Book", "trades", "activeAssetCtx", "instrument_metadata")]
    result = evaluate_copy_vault_replay_readiness(manifests, observed_book_audit={"replay_grade_ready": True})
    assert result["ready"] is True


def test_hvr_0322_required_field():
    assert strategy_required_field_receipt({}, field="dataset_id")["status"] == "REJECTED"


def test_hvr_0323_null_field():
    assert strategy_null_field_receipt({"dataset_id": None}, field="dataset_id")["status"] == "REJECTED"


def test_hvr_0324_field_type():
    assert strategy_field_type_receipt({"count": 1}, field="count", expected_type=int)["status"] == "PROVEN"


def test_hvr_0325_nonfinite():
    assert strategy_finite_receipt(float("nan"))["status"] == "REJECTED"


def test_hvr_0326_cutoff():
    assert strategy_cutoff_receipt(event_ts_ms=10, cutoff_ts_ms=10)["status"] == "PROVEN"


def test_hvr_0327_old_event():
    assert strategy_age_receipt(event_ts_ms=9, oldest_allowed_ts_ms=10)["status"] == "REJECTED"


def test_hvr_0328_duplicate():
    assert strategy_duplicate_receipt(event_ids=["e", "e"])["status"] == "REJECTED"


def test_hvr_0329_retry():
    assert strategy_retry_receipt(attempts=2, max_attempts=3, checkpoint_saved=True)["status"] == "PROVEN"


def test_hvr_0330_replay():
    assert strategy_replay_receipt(outputs=[{"ready": True}, {"ready": True}])["status"] == "PROVEN"


def test_hvr_0331_sha256():
    digest = "a" * 64
    assert strategy_sha256_receipt(actual_sha256=digest, expected_sha256=digest)["status"] == "PROVEN"
    assert strategy_sha256_receipt(actual_sha256="b" * 64, expected_sha256=digest)["status"] == "REJECTED"


def test_hvr_0332_size():
    assert strategy_size_receipt(actual_size=10, expected_size=10)["status"] == "PROVEN"
    assert strategy_size_receipt(actual_size=9, expected_size=10)["status"] == "REJECTED"


def test_hvr_0333_compression():
    assert strategy_compression_receipt(expected_size=10, observed_size=10, complete=True)["status"] == "PROVEN"
    assert strategy_compression_receipt(expected_size=10, observed_size=9, complete=False)["status"] == "REJECTED"


def test_hvr_0334_zip_slip():
    assert strategy_zip_slip_receipt("../outside.json")["status"] == "PROVEN"
    assert strategy_zip_slip_receipt("safe/data.json")["status"] == "REJECTED"


def test_hvr_0335_symlink():
    assert strategy_symlink_receipt(is_symlink=False, within_root=True)["status"] == "PROVEN"
    assert strategy_symlink_receipt(is_symlink=True, within_root=False)["status"] == "REJECTED"


def test_hvr_0336_partial():
    assert strategy_partial_replay_receipt(status="PARTIAL", replayable=False)["status"] == "PROVEN"
    assert strategy_partial_replay_receipt(status="PARTIAL", replayable=True)["status"] == "REJECTED"


def test_hvr_0337_reject():
    assert strategy_reject_validation_receipt(status="REJECT", validated=False)["status"] == "PROVEN"
    assert strategy_reject_validation_receipt(status="REJECT", validated=True)["status"] == "REJECTED"


def test_hvr_0338_unique_counts():
    assert strategy_unique_counts_receipt(total_count=2, unique_count=2, unique_ids=["a", "b"])["status"] == "PROVEN"
    assert strategy_unique_counts_receipt(total_count=2, unique_count=1, unique_ids=["a"])["status"] == "REJECTED"


def test_hvr_0339_manifest():
    assert strategy_manifest_compatibility_receipt(manifest_version="v1", required_version="v1", compatible=True)["status"] == "PROVEN"
    assert strategy_manifest_compatibility_receipt(manifest_version="v1", required_version="v2", compatible=False)["status"] == "REJECTED"


def test_hvr_0340_publication():
    assert strategy_publication_receipt(status="COMPLETE", manifest_committed=True, receipt_written=True)["status"] == "PROVEN"
    assert strategy_publication_receipt(status="PARTIAL", manifest_committed=False, receipt_written=False)["status"] == "REJECTED"


def test_hvr_0340_done_gate_requires_all_checks():
    checks = [
        strategy_cutoff_receipt(event_ts_ms=10, cutoff_ts_ms=10),
        strategy_replay_receipt(outputs=[{"ready": True}, {"ready": True}]),
        strategy_publication_receipt(status="COMPLETE", manifest_committed=True, receipt_written=True),
    ]
    assert strategy_done_receipt(checks=checks)["status"] == "PROVEN"
    assert strategy_done_receipt(checks=checks + [{"status": "REJECTED"}])["status"] == "REJECTED"
