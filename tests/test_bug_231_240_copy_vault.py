from hl_observer.backtesting.copy_vault_evidence_inventory import (
    bbo_depth_checksum_receipt,
    certified_asset_immutability_receipt,
    indirect_rejection_receipt,
    pagination_inventory_receipt,
    release_publication_state_receipt,
    safe_cleanup_receipt,
    segment_gap_receipt,
    shard_time_range_receipt,
    source_clock_receipt,
    dataset_artifact_receipt,
)


def test_bug_231_rejection_cannot_be_published_indirectly():
    assert indirect_rejection_receipt(rejection_state="REJECTED", published_via_index=False)["status"] == "PROVEN"
    assert indirect_rejection_receipt(rejection_state="REJECTED", published_via_index=True)["status"] == "REJECTED"


def test_bug_232_shard_ranges_do_not_overlap():
    assert shard_time_range_receipt([{"start_ms": 0, "end_ms": 10}, {"start_ms": 10, "end_ms": 20}])["status"] == "PROVEN"
    assert shard_time_range_receipt([{"start_ms": 0, "end_ms": 11}, {"start_ms": 10, "end_ms": 20}])["status"] == "REJECTED"


def test_bug_233_segment_has_no_internal_gap():
    assert segment_gap_receipt(segment_start_ms=0, segment_end_ms=20, observed_intervals=[{"start_ms": 0, "end_ms": 10}, {"start_ms": 10, "end_ms": 20}])["status"] == "PROVEN"
    assert segment_gap_receipt(segment_start_ms=0, segment_end_ms=20, observed_intervals=[{"start_ms": 0, "end_ms": 10}, {"start_ms": 11, "end_ms": 20}])["status"] == "REJECTED"


def test_bug_234_bbo_checksum_matches_depth():
    assert bbo_depth_checksum_receipt(checksum_valid=True, observed_depth=2, declared_depth=2)["status"] == "PROVEN"
    assert bbo_depth_checksum_receipt(checksum_valid=True, observed_depth=2, declared_depth=3)["status"] == "REJECTED"


def test_bug_235_certified_asset_is_immutable():
    assert certified_asset_immutability_receipt(certified_sha256="a", current_sha256="a")["status"] == "PROVEN"
    assert certified_asset_immutability_receipt(certified_sha256="a", current_sha256="b")["status"] == "REJECTED"


def test_bug_236_pagination_is_complete():
    assert pagination_inventory_receipt(page_count=2, fetched_pages=2, declared_total=4, fetched_items=4)["status"] == "PROVEN"
    assert pagination_inventory_receipt(page_count=2, fetched_pages=1, declared_total=4, fetched_items=2)["status"] == "REJECTED"


def test_bug_237_in_progress_release_is_not_published():
    assert release_publication_state_receipt(state="PUBLISHED", published=True)["status"] == "PROVEN"
    assert release_publication_state_receipt(state="IN_PROGRESS", published=True)["status"] == "REJECTED"


def test_bug_238_test_artifact_is_not_dataset():
    assert dataset_artifact_receipt(artifact_kind="PRODUCTION", dataset_role="DATASET")["status"] == "PROVEN"
    assert dataset_artifact_receipt(artifact_kind="TEST", dataset_role="DATASET")["status"] == "REJECTED"


def test_bug_239_cleanup_preserves_durable_safe_copy():
    assert safe_cleanup_receipt(safe_paths=["a"], deleted_paths=[], durable_remaining_paths=["a"])["status"] == "PROVEN"
    assert safe_cleanup_receipt(safe_paths=["a"], deleted_paths=["a"], durable_remaining_paths=[])["status"] == "REJECTED"


def test_bug_240_source_clock_is_required():
    assert source_clock_receipt(source_timestamp_ms=1, clock_id="collector-1", clock_sync_verified=True)["status"] == "PROVEN"
    assert source_clock_receipt(source_timestamp_ms=None, clock_id="", clock_sync_verified=False)["status"] == "REJECTED"
