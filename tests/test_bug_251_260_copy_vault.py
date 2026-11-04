from hl_observer.backtesting.copy_vault_evidence_inventory import (
    archive_manifest_bound_receipt,
    catalog_order_receipt,
    certified_cache_receipt,
    crc_error_receipt,
    free_space_receipt,
    physical_space_receipt,
    restore_before_backtest_receipt,
    restore_command_exit_receipt,
    restoration_content_receipt,
    temporary_file_receipt,
)


def test_bug_251_temporary_file_is_not_certified():
    assert temporary_file_receipt(temporary_present=False, content_verified=True)["status"] == "PROVEN"
    assert temporary_file_receipt(temporary_present=True, content_verified=True)["status"] == "REJECTED"


def test_bug_252_restore_reserves_free_space():
    assert free_space_receipt(required_bytes=5, available_bytes=8, reserve_bytes=2)["status"] == "PROVEN"
    assert free_space_receipt(required_bytes=5, available_bytes=6, reserve_bytes=2)["status"] == "REJECTED"


def test_bug_253_catalog_order_is_preserved():
    assert catalog_order_receipt(shard_ids=["a", "b"], catalog_order=["a", "b"])["status"] == "PROVEN"
    assert catalog_order_receipt(shard_ids=["a", "b"], catalog_order=["b", "a"])["status"] == "REJECTED"


def test_bug_254_crc_failure_is_observed():
    assert crc_error_receipt(crc_valid=True, error_observed=False)["status"] == "PROVEN"
    assert crc_error_receipt(crc_valid=False, error_observed=True)["status"] == "PROVEN"
    assert crc_error_receipt(crc_valid=False, error_observed=False)["status"] == "REJECTED"


def test_bug_255_presence_alone_is_not_restore_proof():
    assert restoration_content_receipt(file_present=True, content_verified=True)["status"] == "PROVEN"
    assert restoration_content_receipt(file_present=True, content_verified=False)["status"] == "REJECTED"


def test_bug_256_failed_shard_cannot_exit_zero():
    assert restore_command_exit_receipt(failed_shards=0, exit_code=0)["status"] == "PROVEN"
    assert restore_command_exit_receipt(failed_shards=1, exit_code=0)["status"] == "REJECTED"


def test_bug_257_backtest_waits_for_restore():
    assert restore_before_backtest_receipt(restore_complete=True, backtest_started=True)["status"] == "PROVEN"
    assert restore_before_backtest_receipt(restore_complete=False, backtest_started=True)["status"] == "REJECTED"


def test_bug_258_archive_is_bounded_by_manifest():
    assert archive_manifest_bound_receipt(archive_bytes=5, manifest_max_bytes=6)["status"] == "PROVEN"
    assert archive_manifest_bound_receipt(archive_bytes=7, manifest_max_bytes=6)["status"] == "REJECTED"


def test_bug_259_physical_space_is_checked():
    assert physical_space_receipt(required_bytes=5, reported_free_bytes=6, physical_free_bytes=6, sparse_file_present=False)["status"] == "PROVEN"
    assert physical_space_receipt(required_bytes=7, reported_free_bytes=8, physical_free_bytes=6, sparse_file_present=True)["status"] == "REJECTED"


def test_bug_260_cache_requires_current_certification():
    assert certified_cache_receipt(cache_certified=True, cache_code_sha="a", current_code_sha="a")["status"] == "PROVEN"
    assert certified_cache_receipt(cache_certified=True, cache_code_sha="a", current_code_sha="b")["status"] == "REJECTED"
