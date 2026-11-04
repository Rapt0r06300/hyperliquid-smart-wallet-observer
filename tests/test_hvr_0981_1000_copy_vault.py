"""Fail-closed PNL proof controls for HVR-0981..HVR-1000."""

from hl_observer.control_plane.module_pnl_proof import (
    pnl_age_receipt,
    pnl_checkpoint_receipt,
    pnl_collect_authorization_receipt,
    pnl_cutoff_receipt,
    pnl_done_coverage_receipt,
    pnl_duplicate_receipt,
    pnl_epoch_receipt,
    pnl_field_type_receipt,
    pnl_finite_receipt,
    pnl_hash_receipt,
    pnl_lease_receipt,
    pnl_null_field_receipt,
    pnl_replay_receipt,
    pnl_request_replay_receipt,
    pnl_required_field_receipt,
    pnl_retry_receipt,
    pnl_runner_receipt,
    pnl_single_owner_receipt,
    pnl_stage_order_receipt,
    pnl_state_safety_receipt,
)


def test_hvr_0981_pnl_state_safety_is_explicit() -> None:
    safe = {"paper_only": True, "read_only": True, "real_execution": False, "aggregate_allowed": False}
    assert pnl_state_safety_receipt(safe)["status"] == "PROVEN"
    assert pnl_state_safety_receipt({**safe, "real_execution": True})["status"] == "REJECTED"


def test_hvr_0982_required_field_is_fail_closed() -> None:
    assert pnl_required_field_receipt({"epoch": 1}, field="epoch")["status"] == "PROVEN"
    assert pnl_required_field_receipt({}, field="epoch")["status"] == "REJECTED"


def test_hvr_0983_null_field_is_fail_closed() -> None:
    assert pnl_null_field_receipt({"epoch": 1}, field="epoch")["status"] == "PROVEN"
    assert pnl_null_field_receipt({"epoch": None}, field="epoch")["status"] == "REJECTED"


def test_hvr_0984_field_type_is_strict() -> None:
    assert pnl_field_type_receipt({"epoch": 1}, field="epoch", expected_type=int)["status"] == "PROVEN"
    assert pnl_field_type_receipt({"epoch": True}, field="epoch", expected_type=int)["status"] == "REJECTED"


def test_hvr_0985_finite_value_is_required() -> None:
    assert pnl_finite_receipt(1.25)["status"] == "PROVEN"
    assert pnl_finite_receipt(float("inf"))["status"] == "REJECTED"


def test_hvr_0986_cutoff_boundary_is_inclusive() -> None:
    assert pnl_cutoff_receipt(event_ts_ms=10, cutoff_ts_ms=10)["status"] == "PROVEN"
    assert pnl_cutoff_receipt(event_ts_ms=11, cutoff_ts_ms=10)["status"] == "REJECTED"


def test_hvr_0987_old_event_is_rejected() -> None:
    assert pnl_age_receipt(event_ts_ms=10, oldest_allowed_ts_ms=10)["status"] == "PROVEN"
    assert pnl_age_receipt(event_ts_ms=9, oldest_allowed_ts_ms=10)["status"] == "REJECTED"


def test_hvr_0988_duplicate_events_are_rejected() -> None:
    assert pnl_duplicate_receipt(event_ids=["a", "b"])["status"] == "PROVEN"
    assert pnl_duplicate_receipt(event_ids=["a", "a"])["status"] == "REJECTED"


def test_hvr_0989_retry_requires_checkpoint() -> None:
    assert pnl_retry_receipt(attempts=1, max_attempts=2, checkpoint_saved=True)["status"] == "PROVEN"
    assert pnl_retry_receipt(attempts=3, max_attempts=2, checkpoint_saved=True)["status"] == "REJECTED"


def test_hvr_0990_replay_must_be_identical() -> None:
    assert pnl_replay_receipt(outputs=[{"status": "RUNNING"}, {"status": "RUNNING"}])["status"] == "PROVEN"
    assert pnl_replay_receipt(outputs=[{"status": "RUNNING"}, {"status": "FAILED"}])["status"] == "REJECTED"


def test_hvr_0991_phase_barrier_is_required() -> None:
    assert pnl_stage_order_receipt(creation_phase="ANALYZE", status="RUNNING", phase_barrier=True)["status"] == "PROVEN"
    assert pnl_stage_order_receipt(creation_phase="ANALYZE", status="RUNNING", phase_barrier=False)["status"] == "REJECTED"


def test_hvr_0992_automatic_collect_requires_authorization() -> None:
    assert pnl_collect_authorization_receipt(creation_phase="COLLECT", automatic=True, authorized=True)["status"] == "PROVEN"
    assert pnl_collect_authorization_receipt(creation_phase="COLLECT", automatic=True, authorized=False)["status"] == "REJECTED"


def test_hvr_0993_request_replay_is_rejected() -> None:
    assert pnl_request_replay_receipt(request_ids=["r1"], accepted_request_ids=["r1"])["status"] == "PROVEN"
    assert pnl_request_replay_receipt(request_ids=["r1", "r1"], accepted_request_ids=["r1"])["status"] == "REJECTED"


def test_hvr_0994_epoch_must_be_current() -> None:
    assert pnl_epoch_receipt(observed_epoch=4, current_epoch=4)["status"] == "PROVEN"
    assert pnl_epoch_receipt(observed_epoch=3, current_epoch=4)["status"] == "REJECTED"


def test_hvr_0995_sha_must_match() -> None:
    digest = "a" * 40
    assert pnl_hash_receipt(expected_sha=digest, actual_sha=digest)["status"] == "PROVEN"
    assert pnl_hash_receipt(expected_sha=digest, actual_sha="b" * 40)["status"] == "REJECTED"


def test_hvr_0996_lease_requires_owner_and_time() -> None:
    assert pnl_lease_receipt(worker_id="w1", lease_owner="w1", lease_expires_at_ms=20, now_ms=10)["status"] == "PROVEN"
    assert pnl_lease_receipt(worker_id="w1", lease_owner="w2", lease_expires_at_ms=20, now_ms=10)["status"] == "REJECTED"


def test_hvr_0997_single_owner_blocks_split_brain() -> None:
    assert pnl_single_owner_receipt(owner_ids=["w1"])["status"] == "PROVEN"
    assert pnl_single_owner_receipt(owner_ids=["w1", "w2"])["status"] == "REJECTED"


def test_hvr_0998_checkpoint_must_be_complete() -> None:
    assert pnl_checkpoint_receipt(checkpoint={"saved": True, "epoch": 4}, required_fields=["epoch"])["status"] == "PROVEN"
    assert pnl_checkpoint_receipt(checkpoint={"saved": True}, required_fields=["epoch"])["status"] == "REJECTED"


def test_hvr_0999_self_hosted_runner_is_rejected() -> None:
    assert pnl_runner_receipt(runner_label="ubuntu-latest")["status"] == "PROVEN"
    assert pnl_runner_receipt(runner_label="self-hosted")["status"] == "REJECTED"


def test_hvr_1000_done_requires_coverage() -> None:
    assert pnl_done_coverage_receipt(status="PROVEN", coverage_status="PROVEN", required_proofs=["p1"], completed_proofs=["p1"])["status"] == "PROVEN"
    assert pnl_done_coverage_receipt(status="PROVEN", coverage_status="PROVEN", required_proofs=["p1"], completed_proofs=[])["status"] == "REJECTED"
