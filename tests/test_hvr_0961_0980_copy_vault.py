"""Fail-closed dispatch-receipt controls for HVR-0961..HVR-0980."""

from hl_observer.control_plane.dispatch_receipt import (
    DispatchReceipt,
    dispatch_age_receipt,
    dispatch_checkpoint_receipt,
    dispatch_collect_authorization_receipt,
    dispatch_cutoff_receipt,
    dispatch_done_coverage_receipt,
    dispatch_duplicate_receipt,
    dispatch_epoch_receipt,
    dispatch_field_type_receipt,
    dispatch_finite_receipt,
    dispatch_hash_receipt,
    dispatch_lease_receipt,
    dispatch_null_field_receipt,
    dispatch_replay_receipt,
    dispatch_request_replay_receipt,
    dispatch_required_field_receipt,
    dispatch_retry_receipt,
    dispatch_runner_receipt,
    dispatch_single_owner_receipt,
    dispatch_stage_order_receipt,
    dispatch_state_safety_receipt,
)


def _receipt() -> DispatchReceipt:
    return DispatchReceipt(
        request_id="r1",
        campaign_id="c1",
        main_code_sha="a" * 40,
        dataset_repo_sha="b" * 40,
        creation_phase="COLLECT",
        phase_epoch=1,
        source_collection_epoch=None,
        workflow_run_id=None,
        dispatched_at_utc="2026-01-01T00:00:00Z",
    )


def test_hvr_0961_dispatch_state_positive_and_hostile() -> None:
    assert dispatch_state_safety_receipt(_receipt())["status"] == "PROVEN"
    assert dispatch_state_safety_receipt({"status": "DISPATCHED"})["status"] == "REJECTED"


def test_hvr_0962_required_field_is_fail_closed() -> None:
    assert dispatch_required_field_receipt({"epoch": 1}, field="epoch")["status"] == "PROVEN"
    assert dispatch_required_field_receipt({}, field="epoch")["status"] == "REJECTED"


def test_hvr_0963_null_field_is_fail_closed() -> None:
    assert dispatch_null_field_receipt({"epoch": 1}, field="epoch")["status"] == "PROVEN"
    assert dispatch_null_field_receipt({"epoch": None}, field="epoch")["status"] == "REJECTED"


def test_hvr_0964_field_type_is_strict() -> None:
    assert dispatch_field_type_receipt({"epoch": 1}, field="epoch", expected_type=int)["status"] == "PROVEN"
    assert dispatch_field_type_receipt({"epoch": True}, field="epoch", expected_type=int)["status"] == "REJECTED"


def test_hvr_0965_finite_value_is_required() -> None:
    assert dispatch_finite_receipt(1.25)["status"] == "PROVEN"
    assert dispatch_finite_receipt(float("inf"))["status"] == "REJECTED"


def test_hvr_0966_cutoff_boundary_is_inclusive() -> None:
    assert dispatch_cutoff_receipt(event_ts_ms=10, cutoff_ts_ms=10)["status"] == "PROVEN"
    assert dispatch_cutoff_receipt(event_ts_ms=11, cutoff_ts_ms=10)["status"] == "REJECTED"


def test_hvr_0967_old_event_is_rejected() -> None:
    assert dispatch_age_receipt(event_ts_ms=10, oldest_allowed_ts_ms=10)["status"] == "PROVEN"
    assert dispatch_age_receipt(event_ts_ms=9, oldest_allowed_ts_ms=10)["status"] == "REJECTED"


def test_hvr_0968_duplicate_events_are_rejected() -> None:
    assert dispatch_duplicate_receipt(event_ids=["a", "b"])["status"] == "PROVEN"
    assert dispatch_duplicate_receipt(event_ids=["a", "a"])["status"] == "REJECTED"


def test_hvr_0969_retry_requires_checkpoint() -> None:
    assert dispatch_retry_receipt(attempts=1, max_attempts=2, checkpoint_saved=True)["status"] == "PROVEN"
    assert dispatch_retry_receipt(attempts=3, max_attempts=2, checkpoint_saved=True)["status"] == "REJECTED"


def test_hvr_0970_replay_must_be_identical() -> None:
    assert dispatch_replay_receipt(outputs=[{"status": "RUNNING"}, {"status": "RUNNING"}])["status"] == "PROVEN"
    assert dispatch_replay_receipt(outputs=[{"status": "RUNNING"}, {"status": "FAILED"}])["status"] == "REJECTED"


def test_hvr_0971_phase_barrier_is_required() -> None:
    assert dispatch_stage_order_receipt(creation_phase="ANALYZE", status="RUNNING", phase_barrier=True)["status"] == "PROVEN"
    assert dispatch_stage_order_receipt(creation_phase="ANALYZE", status="RUNNING", phase_barrier=False)["status"] == "REJECTED"


def test_hvr_0972_automatic_collect_requires_authorization() -> None:
    assert dispatch_collect_authorization_receipt(creation_phase="COLLECT", automatic=True, authorized=True)["status"] == "PROVEN"
    assert dispatch_collect_authorization_receipt(creation_phase="COLLECT", automatic=True, authorized=False)["status"] == "REJECTED"


def test_hvr_0973_request_replay_is_rejected() -> None:
    assert dispatch_request_replay_receipt(request_ids=["r1"], accepted_request_ids=["r1"])["status"] == "PROVEN"
    assert dispatch_request_replay_receipt(request_ids=["r1", "r1"], accepted_request_ids=["r1"])["status"] == "REJECTED"


def test_hvr_0974_epoch_must_be_current() -> None:
    assert dispatch_epoch_receipt(observed_epoch=4, current_epoch=4)["status"] == "PROVEN"
    assert dispatch_epoch_receipt(observed_epoch=3, current_epoch=4)["status"] == "REJECTED"


def test_hvr_0975_sha_must_match() -> None:
    digest = "a" * 40
    assert dispatch_hash_receipt(expected_sha=digest, actual_sha=digest)["status"] == "PROVEN"
    assert dispatch_hash_receipt(expected_sha=digest, actual_sha="b" * 40)["status"] == "REJECTED"


def test_hvr_0976_lease_requires_owner_and_time() -> None:
    assert dispatch_lease_receipt(worker_id="w1", lease_owner="w1", lease_expires_at_ms=20, now_ms=10)["status"] == "PROVEN"
    assert dispatch_lease_receipt(worker_id="w1", lease_owner="w2", lease_expires_at_ms=20, now_ms=10)["status"] == "REJECTED"


def test_hvr_0977_single_owner_blocks_split_brain() -> None:
    assert dispatch_single_owner_receipt(owner_ids=["w1"])["status"] == "PROVEN"
    assert dispatch_single_owner_receipt(owner_ids=["w1", "w2"])["status"] == "REJECTED"


def test_hvr_0978_checkpoint_must_be_complete() -> None:
    assert dispatch_checkpoint_receipt(checkpoint={"saved": True, "epoch": 4}, required_fields=["epoch"])["status"] == "PROVEN"
    assert dispatch_checkpoint_receipt(checkpoint={"saved": True}, required_fields=["epoch"])["status"] == "REJECTED"


def test_hvr_0979_self_hosted_runner_is_rejected() -> None:
    assert dispatch_runner_receipt(runner_label="ubuntu-latest")["status"] == "PROVEN"
    assert dispatch_runner_receipt(runner_label="self-hosted")["status"] == "REJECTED"


def test_hvr_0980_done_requires_coverage() -> None:
    assert dispatch_done_coverage_receipt(status="COMPLETE", coverage_status="PROVEN", required_proofs=["p1"], completed_proofs=["p1"])["status"] == "PROVEN"
    assert dispatch_done_coverage_receipt(status="COMPLETE", coverage_status="PROVEN", required_proofs=["p1"], completed_proofs=[])["status"] == "REJECTED"

