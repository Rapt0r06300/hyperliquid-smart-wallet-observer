from hl_observer.datasets.github_release_bridge import (
    release_bridge_age_receipt,
    release_bridge_content_range_receipt,
    release_bridge_cutoff_receipt,
    release_bridge_done_receipt,
    release_bridge_disk_space_receipt,
    release_bridge_duplicate_receipt,
    release_bridge_etag_receipt,
    release_bridge_expansion_receipt,
    release_bridge_finite_receipt,
    release_bridge_field_type_receipt,
    release_bridge_http_error_receipt,
    release_bridge_lease_receipt,
    release_bridge_null_field_receipt,
    release_bridge_preflight_receipt,
    release_bridge_range_receipt,
    release_bridge_replay_receipt,
    release_bridge_required_field_receipt,
    release_bridge_retry_receipt,
    release_bridge_zip_slip_receipt,
)


def _release() -> dict[str, object]:
    return {
        "tag_name": "safe-v1",
        "draft": False,
        "assets": [
            {"id": 1, "name": "manifest.json", "size": 10, "digest": "sha256:" + "a" * 64},
        ],
    }


def test_hvr_0421_release_bridge_baseline_is_safe():
    result = release_bridge_preflight_receipt(_release(), ["manifest.json"])
    assert result["status"] == "PROVEN"


def test_hvr_0422_required_field():
    assert release_bridge_required_field_receipt({"tag": "v1"}, field="tag")["status"] == "PROVEN"
    assert release_bridge_required_field_receipt({}, field="tag")["status"] == "REJECTED"


def test_hvr_0423_null_field():
    assert release_bridge_null_field_receipt({"tag": "v1"}, field="tag")["status"] == "PROVEN"
    assert release_bridge_null_field_receipt({"tag": None}, field="tag")["status"] == "REJECTED"


def test_hvr_0424_field_type():
    assert release_bridge_field_type_receipt({"size": 1}, field="size", expected_type=int)["status"] == "PROVEN"
    assert release_bridge_field_type_receipt({"size": "1"}, field="size", expected_type=int)["status"] == "REJECTED"


def test_hvr_0425_finite_value():
    assert release_bridge_finite_receipt(1.5)["status"] == "PROVEN"
    assert release_bridge_finite_receipt(float("nan"))["status"] == "REJECTED"


def test_hvr_0426_cutoff():
    assert release_bridge_cutoff_receipt(event_ts_ms=10, cutoff_ts_ms=10)["status"] == "PROVEN"
    assert release_bridge_cutoff_receipt(event_ts_ms=11, cutoff_ts_ms=10)["status"] == "REJECTED"


def test_hvr_0427_age():
    assert release_bridge_age_receipt(event_ts_ms=10, oldest_allowed_ts_ms=10)["status"] == "PROVEN"
    assert release_bridge_age_receipt(event_ts_ms=9, oldest_allowed_ts_ms=10)["status"] == "REJECTED"


def test_hvr_0428_duplicate_events():
    assert release_bridge_duplicate_receipt(event_ids=["a", "b"])["status"] == "PROVEN"
    assert release_bridge_duplicate_receipt(event_ids=["a", "a"])["status"] == "REJECTED"


def test_hvr_0429_bounded_retry_requires_checkpoint():
    assert release_bridge_retry_receipt(attempts=2, max_attempts=3, checkpoint_saved=True)["status"] == "PROVEN"
    assert release_bridge_retry_receipt(attempts=4, max_attempts=3, checkpoint_saved=True)["status"] == "REJECTED"


def test_hvr_0430_replay_is_deterministic():
    assert release_bridge_replay_receipt(outputs=[{"assets": 1}, {"assets": 1}])["status"] == "PROVEN"
    assert release_bridge_replay_receipt(outputs=[{"assets": 1}, {"assets": 2}])["status"] == "REJECTED"


def test_hvr_0431_asset_404_is_quarantined():
    assert release_bridge_http_error_receipt(status_code=404)["status"] == "PROVEN"


def test_hvr_0432_rate_limit_requires_retry_after():
    assert release_bridge_http_error_receipt(status_code=429, retry_after_seconds=2)["status"] == "PROVEN"
    assert release_bridge_http_error_receipt(status_code=429)["status"] == "REJECTED"


def test_hvr_0433_range_must_be_honored():
    assert release_bridge_range_receipt(requested_start=4, observed_start=4, range_honored=True)["status"] == "PROVEN"
    assert release_bridge_range_receipt(requested_start=4, observed_start=0, range_honored=False)["status"] == "REJECTED"


def test_hvr_0434_content_range_must_match():
    assert release_bridge_content_range_receipt(expected_start=4, observed_start=4, expected_end=9, observed_end=9)["status"] == "PROVEN"
    assert release_bridge_content_range_receipt(expected_start=4, observed_start=0, expected_end=9, observed_end=9)["status"] == "REJECTED"


def test_hvr_0435_changed_etag_invalidates_cache():
    result = release_bridge_etag_receipt(previous_etag="old", current_etag="new")
    assert result["status"] == "PROVEN"
    assert result["cache_invalidated"] is True


def test_hvr_0436_disk_space_is_checked():
    assert release_bridge_disk_space_receipt(required_bytes=10, available_bytes=10)["status"] == "PROVEN"
    assert release_bridge_disk_space_receipt(required_bytes=11, available_bytes=10)["status"] == "REJECTED"


def test_hvr_0437_zip_slip_is_refused():
    assert release_bridge_zip_slip_receipt("../escape.bin")["status"] == "PROVEN"
    assert release_bridge_zip_slip_receipt("safe/data.bin")["status"] == "REJECTED"


def test_hvr_0438_expansion_is_bounded():
    assert release_bridge_expansion_receipt(observed_bytes=10, max_bytes=10, complete=True)["status"] == "PROVEN"
    assert release_bridge_expansion_receipt(observed_bytes=11, max_bytes=10, complete=True)["status"] == "REJECTED"


def test_hvr_0439_only_one_sync_lease_is_allowed():
    assert release_bridge_lease_receipt(active_leases=1, lease_token_present=True)["status"] == "PROVEN"
    assert release_bridge_lease_receipt(active_leases=2, lease_token_present=True)["status"] == "REJECTED"


def test_hvr_0440_incomplete_release_is_fail_closed():
    assert release_bridge_preflight_receipt({"tag_name": "safe-v1", "draft": False, "assets": []}, ["manifest.json"])["status"] == "REJECTED"


def test_hvr_0441_release_bridge_done_requires_all_proven_gates():
    checks = [
        release_bridge_required_field_receipt({"tag": "v1"}, field="tag"),
        release_bridge_replay_receipt(outputs=[{"assets": 1}, {"assets": 1}]),
        release_bridge_lease_receipt(active_leases=1, lease_token_present=True),
    ]
    assert release_bridge_done_receipt(checks=checks)["status"] == "PROVEN"
    assert release_bridge_done_receipt(checks=checks[:-1] + [{"status": "PROVEN"}])["status"] == "REJECTED"
