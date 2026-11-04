from tools.sync_complete_clone import (
    sync_clone_age_receipt,
    sync_clone_content_range_receipt,
    sync_clone_cutoff_receipt,
    sync_clone_done_receipt,
    sync_clone_disk_space_receipt,
    sync_clone_duplicate_receipt,
    sync_clone_etag_receipt,
    sync_clone_expansion_receipt,
    sync_clone_finite_receipt,
    sync_clone_field_type_receipt,
    sync_clone_http_error_receipt,
    sync_clone_lease_receipt,
    sync_clone_null_field_receipt,
    sync_clone_preflight_receipt,
    sync_clone_range_receipt,
    sync_clone_replay_receipt,
    sync_clone_required_field_receipt,
    sync_clone_retry_receipt,
    sync_clone_zip_slip_receipt,
)


def _state() -> dict[str, object]:
    return {
        "branch": "main",
        "tracked_clean": True,
        "origin_trusted": True,
        "force_push": False,
        "reset": False,
        "clean": False,
    }


def test_hvr_0481_sync_clone_baseline_is_safe():
    assert sync_clone_preflight_receipt(_state())["status"] == "PROVEN"


def test_hvr_0482_required_field():
    assert sync_clone_required_field_receipt({"branch": "main"}, field="branch")["status"] == "PROVEN"
    assert sync_clone_required_field_receipt({}, field="branch")["status"] == "REJECTED"


def test_hvr_0483_null_field():
    assert sync_clone_null_field_receipt({"branch": "main"}, field="branch")["status"] == "PROVEN"
    assert sync_clone_null_field_receipt({"branch": None}, field="branch")["status"] == "REJECTED"


def test_hvr_0484_field_type():
    assert sync_clone_field_type_receipt({"clean": False}, field="clean", expected_type=bool)["status"] == "PROVEN"
    assert sync_clone_field_type_receipt({"clean": "false"}, field="clean", expected_type=bool)["status"] == "REJECTED"


def test_hvr_0485_finite_value():
    assert sync_clone_finite_receipt(1.5)["status"] == "PROVEN"
    assert sync_clone_finite_receipt(float("inf"))["status"] == "REJECTED"


def test_hvr_0486_cutoff():
    assert sync_clone_cutoff_receipt(event_ts_ms=10, cutoff_ts_ms=10)["status"] == "PROVEN"
    assert sync_clone_cutoff_receipt(event_ts_ms=11, cutoff_ts_ms=10)["status"] == "REJECTED"


def test_hvr_0487_age():
    assert sync_clone_age_receipt(event_ts_ms=10, oldest_allowed_ts_ms=10)["status"] == "PROVEN"
    assert sync_clone_age_receipt(event_ts_ms=9, oldest_allowed_ts_ms=10)["status"] == "REJECTED"


def test_hvr_0488_duplicate_events():
    assert sync_clone_duplicate_receipt(event_ids=["a", "b"])["status"] == "PROVEN"
    assert sync_clone_duplicate_receipt(event_ids=["a", "a"])["status"] == "REJECTED"


def test_hvr_0489_bounded_retry_requires_checkpoint():
    assert sync_clone_retry_receipt(attempts=2, max_attempts=3, checkpoint_saved=True)["status"] == "PROVEN"
    assert sync_clone_retry_receipt(attempts=4, max_attempts=3, checkpoint_saved=True)["status"] == "REJECTED"


def test_hvr_0490_replay_is_deterministic():
    assert sync_clone_replay_receipt(outputs=[{"head": "a"}, {"head": "a"}])["status"] == "PROVEN"
    assert sync_clone_replay_receipt(outputs=[{"head": "a"}, {"head": "b"}])["status"] == "REJECTED"


def test_hvr_0491_asset_404_is_quarantined():
    assert sync_clone_http_error_receipt(status_code=404)["status"] == "PROVEN"


def test_hvr_0492_rate_limit_requires_retry_after():
    assert sync_clone_http_error_receipt(status_code=429, retry_after_seconds=2)["status"] == "PROVEN"
    assert sync_clone_http_error_receipt(status_code=429)["status"] == "REJECTED"


def test_hvr_0493_range_must_be_honored():
    assert sync_clone_range_receipt(requested_start=4, observed_start=4, range_honored=True)["status"] == "PROVEN"
    assert sync_clone_range_receipt(requested_start=4, observed_start=0, range_honored=False)["status"] == "REJECTED"


def test_hvr_0494_content_range_must_match():
    assert sync_clone_content_range_receipt(expected_start=4, observed_start=4, expected_end=9, observed_end=9)["status"] == "PROVEN"
    assert sync_clone_content_range_receipt(expected_start=4, observed_start=0, expected_end=9, observed_end=9)["status"] == "REJECTED"


def test_hvr_0495_changed_etag_invalidates_cache():
    result = sync_clone_etag_receipt(previous_etag="old", current_etag="new")
    assert result["status"] == "PROVEN"
    assert result["cache_invalidated"] is True


def test_hvr_0496_disk_space_is_checked():
    assert sync_clone_disk_space_receipt(required_bytes=10, available_bytes=10)["status"] == "PROVEN"
    assert sync_clone_disk_space_receipt(required_bytes=11, available_bytes=10)["status"] == "REJECTED"


def test_hvr_0497_zip_slip_is_refused():
    assert sync_clone_zip_slip_receipt("../escape.bin")["status"] == "PROVEN"
    assert sync_clone_zip_slip_receipt("safe/data.bin")["status"] == "REJECTED"


def test_hvr_0498_expansion_is_bounded():
    assert sync_clone_expansion_receipt(observed_bytes=10, max_bytes=10, complete=True)["status"] == "PROVEN"
    assert sync_clone_expansion_receipt(observed_bytes=11, max_bytes=10, complete=True)["status"] == "REJECTED"


def test_hvr_0499_only_one_sync_lease_is_allowed():
    assert sync_clone_lease_receipt(active_leases=1, lease_token_present=True)["status"] == "PROVEN"
    assert sync_clone_lease_receipt(active_leases=2, lease_token_present=True)["status"] == "REJECTED"


def test_hvr_0500_unsafe_state_is_fail_closed():
    state = _state()
    state["branch"] = "codex/research"
    assert sync_clone_preflight_receipt(state)["status"] == "REJECTED"


def test_hvr_0501_sync_clone_done_requires_all_proven_gates():
    checks = [
        sync_clone_required_field_receipt({"branch": "main"}, field="branch"),
        sync_clone_replay_receipt(outputs=[{"head": "a"}, {"head": "a"}]),
        sync_clone_lease_receipt(active_leases=1, lease_token_present=True),
    ]
    assert sync_clone_done_receipt(checks=checks)["status"] == "PROVEN"
    assert sync_clone_done_receipt(checks=checks[:-1] + [{"status": "PROVEN"}])["status"] == "REJECTED"
