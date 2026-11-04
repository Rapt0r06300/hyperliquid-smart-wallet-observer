from hl_observer.ops.copy_vault_storage_controls import (
    disable_raw_vs_bounded_receipt,
    observed_vs_certified_fee_receipt,
    raw_file_quota_receipt,
    replay_archive_writer_receipt,
    session_journal_integrity_receipt,
    single_dataset_source_receipt,
    sql_operational_vs_replay_grade_receipt,
    tape_rotation_receipt,
    windows_path_receipt,
)


def test_lch122_separates_operational_and_replay_storage() -> None:
    assert sql_operational_vs_replay_grade_receipt(
        [{"role": "operational"}, {"role": "replay_grade", "immutable": True, "safe": True, "manifest_hash": "a" * 64}]
    )["status"] == "PROVEN"
    assert sql_operational_vs_replay_grade_receipt(
        [{"role": "replay_grade", "immutable": False, "safe": True, "manifest_hash": "a" * 64}]
    )["status"] == "REJECTED"


def test_lch123_enforces_ten_gib_raw_quota() -> None:
    assert raw_file_quota_receipt([{"path": "a", "size_bytes": 10}], max_bytes=10)["status"] == "PROVEN"
    assert raw_file_quota_receipt([{"path": "a", "size_bytes": 11}], max_bytes=10)["status"] == "REJECTED"


def test_lch124_makes_raw_storage_modes_explicit() -> None:
    assert disable_raw_vs_bounded_receipt(
        {"disable_raw_storage": True, "bounded_files_enabled": True, "bounded_quota_bytes": 100}
    )["status"] == "PROVEN"
    assert disable_raw_vs_bounded_receipt(
        {"disable_raw_storage": True, "bounded_files_enabled": True}
    )["status"] == "UNMEASURABLE"


def test_lch125_requires_compaction_and_rotation() -> None:
    row = {"size_bytes": 200, "rotated": True, "closed": True, "compacted": True}
    assert tape_rotation_receipt([row], max_bytes=100)["status"] == "PROVEN"
    row["rotated"] = False
    assert tape_rotation_receipt([row], max_bytes=100)["status"] == "REJECTED"


def test_lch126_blocks_replay_while_writer_is_active() -> None:
    assert replay_archive_writer_receipt({"writer_active": False, "archive_finalized": True})["status"] == "PROVEN"
    assert replay_archive_writer_receipt({"writer_active": True, "archive_finalized": True})["status"] == "REJECTED"


def test_lch127_detects_session_journal_corruption() -> None:
    rows = [
        {"sequence": 1, "previous_hash": "0" * 64, "entry_hash": "1" * 64},
        {"sequence": 2, "previous_hash": "1" * 64, "entry_hash": "2" * 64},
    ]
    assert session_journal_integrity_receipt(rows)["status"] == "PROVEN"
    rows[1]["previous_hash"] = "3" * 64
    assert session_journal_integrity_receipt(rows)["status"] == "REJECTED"


def test_lch128_accepts_long_unicode_paths_without_io() -> None:
    assert windows_path_receipt([{"path": "C:/données/" + "x" * 300}])["status"] == "PROVEN"
    assert windows_path_receipt([{"path": "bad\x00path"}])["status"] == "UNMEASURABLE"


def test_lch129_requires_one_dataset_source() -> None:
    rows = [{"dataset_id": "d1", "manifest_hash": "a" * 64}, {"dataset_id": "d1", "manifest_hash": "a" * 64}]
    assert single_dataset_source_receipt(rows)["status"] == "PROVEN"
    rows[1]["dataset_id"] = "d2"
    assert single_dataset_source_receipt(rows)["status"] == "REJECTED"


def test_lch130_separates_observed_metrics_and_certified_fees() -> None:
    observed = {"observed_spread_bps": 1.0, "observed_slippage_bps": 2.0, "sample_count": 10}
    fees = {"fee_bps": 4.0, "schedule_id": "tier-1", "certified_at_ms": 100}
    assert observed_vs_certified_fee_receipt(observed, fees)["status"] == "PROVEN"
    assert observed_vs_certified_fee_receipt(observed, {"fee_bps": 4.0})["status"] == "UNMEASURABLE"
