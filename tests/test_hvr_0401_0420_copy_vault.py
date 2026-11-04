from hl_observer.datasets.progress_downloader import (
    downloader_age_receipt,
    downloader_content_range_receipt,
    downloader_cutoff_receipt,
    downloader_disk_space_receipt,
    downloader_duplicate_receipt,
    downloader_etag_receipt,
    downloader_expansion_receipt,
    downloader_finite_receipt,
    downloader_field_type_receipt,
    downloader_http_error_receipt,
    downloader_lease_receipt,
    downloader_null_field_receipt,
    downloader_preflight_receipt,
    downloader_range_receipt,
    downloader_replay_receipt,
    downloader_required_field_receipt,
    downloader_retry_receipt,
    downloader_zip_slip_receipt,
)


def _plan() -> dict[str, object]:
    return {
        "asset_count": 2,
        "logical_asset_bytes": 10,
        "verified_cache_bytes": 4,
        "partial_cache_bytes": 2,
        "remaining_network_bytes": 4,
        "verified_cache_names": ["a"],
        "partial_cache_names": ["b"],
        "invalid_cached_names": [],
    }


def test_hvr_0401_downloader_baseline_preflight_is_safe():
    result = downloader_preflight_receipt(_plan())
    assert result["status"] == "PROVEN"


def test_hvr_0402_required_field():
    assert downloader_required_field_receipt({"etag": "x"}, field="etag")["status"] == "PROVEN"
    assert downloader_required_field_receipt({}, field="etag")["status"] == "REJECTED"


def test_hvr_0403_null_field():
    assert downloader_null_field_receipt({"etag": "x"}, field="etag")["status"] == "PROVEN"
    assert downloader_null_field_receipt({"etag": None}, field="etag")["status"] == "REJECTED"


def test_hvr_0404_field_type():
    assert downloader_field_type_receipt({"status": 200}, field="status", expected_type=int)["status"] == "PROVEN"
    assert downloader_field_type_receipt({"status": "200"}, field="status", expected_type=int)["status"] == "REJECTED"


def test_hvr_0405_finite_value():
    assert downloader_finite_receipt(1.5)["status"] == "PROVEN"
    assert downloader_finite_receipt(float("inf"))["status"] == "REJECTED"


def test_hvr_0406_cutoff():
    assert downloader_cutoff_receipt(event_ts_ms=10, cutoff_ts_ms=10)["status"] == "PROVEN"
    assert downloader_cutoff_receipt(event_ts_ms=11, cutoff_ts_ms=10)["status"] == "REJECTED"


def test_hvr_0407_age():
    assert downloader_age_receipt(event_ts_ms=10, oldest_allowed_ts_ms=10)["status"] == "PROVEN"
    assert downloader_age_receipt(event_ts_ms=9, oldest_allowed_ts_ms=10)["status"] == "REJECTED"


def test_hvr_0408_duplicate_events():
    assert downloader_duplicate_receipt(event_ids=["a", "b"])["status"] == "PROVEN"
    assert downloader_duplicate_receipt(event_ids=["a", "a"])["status"] == "REJECTED"


def test_hvr_0409_bounded_retry_requires_checkpoint():
    assert downloader_retry_receipt(attempts=2, max_attempts=3, checkpoint_saved=True)["status"] == "PROVEN"
    assert downloader_retry_receipt(attempts=4, max_attempts=3, checkpoint_saved=True)["status"] == "REJECTED"


def test_hvr_0410_replay_is_deterministic():
    assert downloader_replay_receipt(outputs=[{"bytes": 1}, {"bytes": 1}])["status"] == "PROVEN"
    assert downloader_replay_receipt(outputs=[{"bytes": 1}, {"bytes": 2}])["status"] == "REJECTED"


def test_hvr_0411_asset_404_is_quarantined():
    assert downloader_http_error_receipt(status_code=404)["status"] == "PROVEN"


def test_hvr_0412_rate_limit_requires_retry_after():
    assert downloader_http_error_receipt(status_code=429, retry_after_seconds=2)["status"] == "PROVEN"
    assert downloader_http_error_receipt(status_code=429)["status"] == "REJECTED"


def test_hvr_0413_range_must_be_honored():
    assert downloader_range_receipt(requested_start=4, observed_start=4, range_honored=True)["status"] == "PROVEN"
    assert downloader_range_receipt(requested_start=4, observed_start=0, range_honored=False)["status"] == "REJECTED"


def test_hvr_0414_content_range_must_match():
    assert downloader_content_range_receipt(expected_start=4, observed_start=4, expected_end=9, observed_end=9)["status"] == "PROVEN"
    assert downloader_content_range_receipt(expected_start=4, observed_start=0, expected_end=9, observed_end=9)["status"] == "REJECTED"


def test_hvr_0415_changed_etag_invalidates_cache():
    result = downloader_etag_receipt(previous_etag="old", current_etag="new")
    assert result["status"] == "PROVEN"
    assert result["cache_invalidated"] is True


def test_hvr_0416_disk_space_is_checked():
    assert downloader_disk_space_receipt(required_bytes=10, available_bytes=10)["status"] == "PROVEN"
    assert downloader_disk_space_receipt(required_bytes=11, available_bytes=10)["status"] == "REJECTED"


def test_hvr_0417_zip_slip_is_refused():
    assert downloader_zip_slip_receipt("../escape.bin")["status"] == "PROVEN"
    assert downloader_zip_slip_receipt("safe/data.bin")["status"] == "REJECTED"


def test_hvr_0418_expansion_is_bounded():
    assert downloader_expansion_receipt(observed_bytes=10, max_bytes=10, complete=True)["status"] == "PROVEN"
    assert downloader_expansion_receipt(observed_bytes=11, max_bytes=10, complete=True)["status"] == "REJECTED"


def test_hvr_0419_only_one_sync_lease_is_allowed():
    assert downloader_lease_receipt(active_leases=1, lease_token_present=True)["status"] == "PROVEN"
    assert downloader_lease_receipt(active_leases=2, lease_token_present=True)["status"] == "REJECTED"


def test_hvr_0420_invalid_plan_is_fail_closed():
    assert downloader_preflight_receipt({"asset_count": 1})["status"] == "REJECTED"
