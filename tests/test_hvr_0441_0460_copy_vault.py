from hl_observer.datasets.v2_pipeline import V2_REPOSITORY
from hl_observer.datasets.v2_reader import (
    reader_age_receipt,
    reader_content_range_receipt,
    reader_cutoff_receipt,
    reader_disk_space_receipt,
    reader_duplicate_receipt,
    reader_etag_receipt,
    reader_expansion_receipt,
    reader_finite_receipt,
    reader_field_type_receipt,
    reader_http_error_receipt,
    reader_lease_receipt,
    reader_null_field_receipt,
    reader_preflight_receipt,
    reader_range_receipt,
    reader_replay_receipt,
    reader_required_field_receipt,
    reader_retry_receipt,
    reader_zip_slip_receipt,
)


def _manifest() -> dict[str, object]:
    return {
        "quality_status": "SAFE",
        "replay_compatible": True,
        "validation_allowed": True,
        "asset_verified": True,
        "release": {
            "repository": V2_REPOSITORY,
            "asset_id": 1,
            "asset_name": "shard.jsonl.gz",
        },
    }


def test_hvr_0441_reader_baseline_is_safe():
    assert reader_preflight_receipt(_manifest())["status"] == "PROVEN"


def test_hvr_0442_required_field():
    assert reader_required_field_receipt({"dataset_id": "d1"}, field="dataset_id")["status"] == "PROVEN"
    assert reader_required_field_receipt({}, field="dataset_id")["status"] == "REJECTED"


def test_hvr_0443_null_field():
    assert reader_null_field_receipt({"dataset_id": "d1"}, field="dataset_id")["status"] == "PROVEN"
    assert reader_null_field_receipt({"dataset_id": None}, field="dataset_id")["status"] == "REJECTED"


def test_hvr_0444_field_type():
    assert reader_field_type_receipt({"release_id": 1}, field="release_id", expected_type=int)["status"] == "PROVEN"
    assert reader_field_type_receipt({"release_id": "1"}, field="release_id", expected_type=int)["status"] == "REJECTED"


def test_hvr_0445_finite_value():
    assert reader_finite_receipt(1.5)["status"] == "PROVEN"
    assert reader_finite_receipt(float("nan"))["status"] == "REJECTED"


def test_hvr_0446_cutoff():
    assert reader_cutoff_receipt(event_ts_ms=10, cutoff_ts_ms=10)["status"] == "PROVEN"
    assert reader_cutoff_receipt(event_ts_ms=11, cutoff_ts_ms=10)["status"] == "REJECTED"


def test_hvr_0447_age():
    assert reader_age_receipt(event_ts_ms=10, oldest_allowed_ts_ms=10)["status"] == "PROVEN"
    assert reader_age_receipt(event_ts_ms=9, oldest_allowed_ts_ms=10)["status"] == "REJECTED"


def test_hvr_0448_duplicate_events():
    assert reader_duplicate_receipt(event_ids=["a", "b"])["status"] == "PROVEN"
    assert reader_duplicate_receipt(event_ids=["a", "a"])["status"] == "REJECTED"


def test_hvr_0449_bounded_retry_requires_checkpoint():
    assert reader_retry_receipt(attempts=2, max_attempts=3, checkpoint_saved=True)["status"] == "PROVEN"
    assert reader_retry_receipt(attempts=4, max_attempts=3, checkpoint_saved=True)["status"] == "REJECTED"


def test_hvr_0450_replay_is_deterministic():
    assert reader_replay_receipt(outputs=[{"rows": 1}, {"rows": 1}])["status"] == "PROVEN"
    assert reader_replay_receipt(outputs=[{"rows": 1}, {"rows": 2}])["status"] == "REJECTED"


def test_hvr_0451_asset_404_is_quarantined():
    assert reader_http_error_receipt(status_code=404)["status"] == "PROVEN"


def test_hvr_0452_rate_limit_requires_retry_after():
    assert reader_http_error_receipt(status_code=429, retry_after_seconds=2)["status"] == "PROVEN"
    assert reader_http_error_receipt(status_code=429)["status"] == "REJECTED"


def test_hvr_0453_range_must_be_honored():
    assert reader_range_receipt(requested_start=4, observed_start=4, range_honored=True)["status"] == "PROVEN"
    assert reader_range_receipt(requested_start=4, observed_start=0, range_honored=False)["status"] == "REJECTED"


def test_hvr_0454_content_range_must_match():
    assert reader_content_range_receipt(expected_start=4, observed_start=4, expected_end=9, observed_end=9)["status"] == "PROVEN"
    assert reader_content_range_receipt(expected_start=4, observed_start=0, expected_end=9, observed_end=9)["status"] == "REJECTED"


def test_hvr_0455_changed_etag_invalidates_cache():
    result = reader_etag_receipt(previous_etag="old", current_etag="new")
    assert result["status"] == "PROVEN"
    assert result["cache_invalidated"] is True


def test_hvr_0456_disk_space_is_checked():
    assert reader_disk_space_receipt(required_bytes=10, available_bytes=10)["status"] == "PROVEN"
    assert reader_disk_space_receipt(required_bytes=11, available_bytes=10)["status"] == "REJECTED"


def test_hvr_0457_zip_slip_is_refused():
    assert reader_zip_slip_receipt("../escape.bin")["status"] == "PROVEN"
    assert reader_zip_slip_receipt("safe/data.bin")["status"] == "REJECTED"


def test_hvr_0458_expansion_is_bounded():
    assert reader_expansion_receipt(observed_bytes=10, max_bytes=10, complete=True)["status"] == "PROVEN"
    assert reader_expansion_receipt(observed_bytes=11, max_bytes=10, complete=True)["status"] == "REJECTED"


def test_hvr_0459_only_one_sync_lease_is_allowed():
    assert reader_lease_receipt(active_leases=1, lease_token_present=True)["status"] == "PROVEN"
    assert reader_lease_receipt(active_leases=2, lease_token_present=True)["status"] == "REJECTED"


def test_hvr_0460_invalid_manifest_is_fail_closed():
    assert reader_preflight_receipt({"quality_status": "PARTIAL"})["status"] == "REJECTED"
