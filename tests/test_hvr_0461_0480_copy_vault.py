from hl_observer.datasets.replay_workspace import (
    replay_workspace_age_receipt,
    replay_workspace_content_range_receipt,
    replay_workspace_cutoff_receipt,
    replay_workspace_done_receipt,
    replay_workspace_disk_space_receipt,
    replay_workspace_duplicate_receipt,
    replay_workspace_etag_receipt,
    replay_workspace_expansion_receipt,
    replay_workspace_finite_receipt,
    replay_workspace_field_type_receipt,
    replay_workspace_http_error_receipt,
    replay_workspace_lease_receipt,
    replay_workspace_null_field_receipt,
    replay_workspace_preflight_receipt,
    replay_workspace_range_receipt,
    replay_workspace_replay_receipt,
    replay_workspace_required_field_receipt,
    replay_workspace_retry_receipt,
    replay_workspace_zip_slip_receipt,
)


def _report() -> dict[str, object]:
    return {
        "status": "READY",
        "paper_only": True,
        "real_execution": False,
        "mainnet_execution": False,
        "testnet_execution": False,
        "untrusted_dataset_guard": {"status": "PROVEN"},
    }


def test_hvr_0461_replay_workspace_baseline_is_safe():
    assert replay_workspace_preflight_receipt(_report())["status"] == "PROVEN"


def test_hvr_0462_required_field():
    assert replay_workspace_required_field_receipt({"workspace": "x"}, field="workspace")["status"] == "PROVEN"
    assert replay_workspace_required_field_receipt({}, field="workspace")["status"] == "REJECTED"


def test_hvr_0463_null_field():
    assert replay_workspace_null_field_receipt({"workspace": "x"}, field="workspace")["status"] == "PROVEN"
    assert replay_workspace_null_field_receipt({"workspace": None}, field="workspace")["status"] == "REJECTED"


def test_hvr_0464_field_type():
    assert replay_workspace_field_type_receipt({"attempts": 1}, field="attempts", expected_type=int)["status"] == "PROVEN"
    assert replay_workspace_field_type_receipt({"attempts": "1"}, field="attempts", expected_type=int)["status"] == "REJECTED"


def test_hvr_0465_finite_value():
    assert replay_workspace_finite_receipt(1.5)["status"] == "PROVEN"
    assert replay_workspace_finite_receipt(float("inf"))["status"] == "REJECTED"


def test_hvr_0466_cutoff():
    assert replay_workspace_cutoff_receipt(event_ts_ms=10, cutoff_ts_ms=10)["status"] == "PROVEN"
    assert replay_workspace_cutoff_receipt(event_ts_ms=11, cutoff_ts_ms=10)["status"] == "REJECTED"


def test_hvr_0467_age():
    assert replay_workspace_age_receipt(event_ts_ms=10, oldest_allowed_ts_ms=10)["status"] == "PROVEN"
    assert replay_workspace_age_receipt(event_ts_ms=9, oldest_allowed_ts_ms=10)["status"] == "REJECTED"


def test_hvr_0468_duplicate_events():
    assert replay_workspace_duplicate_receipt(event_ids=["a", "b"])["status"] == "PROVEN"
    assert replay_workspace_duplicate_receipt(event_ids=["a", "a"])["status"] == "REJECTED"


def test_hvr_0469_bounded_retry_requires_checkpoint():
    assert replay_workspace_retry_receipt(attempts=2, max_attempts=3, checkpoint_saved=True)["status"] == "PROVEN"
    assert replay_workspace_retry_receipt(attempts=4, max_attempts=3, checkpoint_saved=True)["status"] == "REJECTED"


def test_hvr_0470_replay_is_deterministic():
    assert replay_workspace_replay_receipt(outputs=[{"rows": 1}, {"rows": 1}])["status"] == "PROVEN"
    assert replay_workspace_replay_receipt(outputs=[{"rows": 1}, {"rows": 2}])["status"] == "REJECTED"


def test_hvr_0471_asset_404_is_quarantined():
    assert replay_workspace_http_error_receipt(status_code=404)["status"] == "PROVEN"


def test_hvr_0472_rate_limit_requires_retry_after():
    assert replay_workspace_http_error_receipt(status_code=429, retry_after_seconds=2)["status"] == "PROVEN"
    assert replay_workspace_http_error_receipt(status_code=429)["status"] == "REJECTED"


def test_hvr_0473_range_must_be_honored():
    assert replay_workspace_range_receipt(requested_start=4, observed_start=4, range_honored=True)["status"] == "PROVEN"
    assert replay_workspace_range_receipt(requested_start=4, observed_start=0, range_honored=False)["status"] == "REJECTED"


def test_hvr_0474_content_range_must_match():
    assert replay_workspace_content_range_receipt(expected_start=4, observed_start=4, expected_end=9, observed_end=9)["status"] == "PROVEN"
    assert replay_workspace_content_range_receipt(expected_start=4, observed_start=0, expected_end=9, observed_end=9)["status"] == "REJECTED"


def test_hvr_0475_changed_etag_invalidates_cache():
    result = replay_workspace_etag_receipt(previous_etag="old", current_etag="new")
    assert result["status"] == "PROVEN"
    assert result["cache_invalidated"] is True


def test_hvr_0476_disk_space_is_checked():
    assert replay_workspace_disk_space_receipt(required_bytes=10, available_bytes=10)["status"] == "PROVEN"
    assert replay_workspace_disk_space_receipt(required_bytes=11, available_bytes=10)["status"] == "REJECTED"


def test_hvr_0477_zip_slip_is_refused():
    assert replay_workspace_zip_slip_receipt("../escape.bin")["status"] == "PROVEN"
    assert replay_workspace_zip_slip_receipt("safe/data.bin")["status"] == "REJECTED"


def test_hvr_0478_expansion_is_bounded():
    assert replay_workspace_expansion_receipt(observed_bytes=10, max_bytes=10, complete=True)["status"] == "PROVEN"
    assert replay_workspace_expansion_receipt(observed_bytes=11, max_bytes=10, complete=True)["status"] == "REJECTED"


def test_hvr_0479_only_one_sync_lease_is_allowed():
    assert replay_workspace_lease_receipt(active_leases=1, lease_token_present=True)["status"] == "PROVEN"
    assert replay_workspace_lease_receipt(active_leases=2, lease_token_present=True)["status"] == "REJECTED"


def test_hvr_0480_invalid_workspace_report_is_fail_closed():
    assert replay_workspace_preflight_receipt({"status": "READY"})["status"] == "REJECTED"


def test_hvr_0481_replay_workspace_done_requires_all_proven_gates():
    checks = [
        replay_workspace_required_field_receipt({"workspace": "x"}, field="workspace"),
        replay_workspace_replay_receipt(outputs=[{"rows": 1}, {"rows": 1}]),
        replay_workspace_lease_receipt(active_leases=1, lease_token_present=True),
    ]
    assert replay_workspace_done_receipt(checks=checks)["status"] == "PROVEN"
    assert replay_workspace_done_receipt(checks=checks[:-1] + [{"status": "PROVEN"}])["status"] == "REJECTED"
