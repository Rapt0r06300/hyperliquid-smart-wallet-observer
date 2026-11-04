"""Fail-closed phase-controller controls for HVR-0921..HVR-0940."""

from hl_observer.control_plane.phase_controller import (
    controller_age_receipt,
    controller_checkpoint_receipt,
    controller_collect_authorization_receipt,
    controller_cutoff_receipt,
    controller_done_coverage_receipt,
    controller_duplicate_receipt,
    controller_epoch_receipt,
    controller_field_type_receipt,
    controller_finite_receipt,
    controller_hash_receipt,
    controller_lease_receipt,
    controller_null_field_receipt,
    controller_replay_receipt,
    controller_request_replay_receipt,
    controller_required_field_receipt,
    controller_retry_receipt,
    controller_runner_receipt,
    controller_single_owner_receipt,
    controller_stage_order_receipt,
    controller_state_safety_receipt,
)
from hl_observer.control_plane.phase_state import AlinaPhaseState


def _state() -> AlinaPhaseState:
    return AlinaPhaseState(
        phase="ANALYZE",
        epoch=4,
        collection_started_at_utc="2026-01-01T00:00:00Z",
        collection_cutoff_at_utc="2026-01-01T01:00:00Z",
        source_collection_epoch=4,
        analysis_stage="DRAIN",
    )


def test_hvr_0921_controller_state_positive_and_hostile() -> None:
    assert controller_state_safety_receipt(_state())["status"] == "PROVEN"
    assert controller_state_safety_receipt({"phase": "ANALYZE"})["status"] == "REJECTED"


def test_hvr_0922_required_field_is_fail_closed() -> None:
    assert controller_required_field_receipt({"epoch": 1}, field="epoch")["status"] == "PROVEN"
    assert controller_required_field_receipt({}, field="epoch")["status"] == "REJECTED"


def test_hvr_0923_null_field_is_fail_closed() -> None:
    assert controller_null_field_receipt({"epoch": 1}, field="epoch")["status"] == "PROVEN"
    assert controller_null_field_receipt({"epoch": None}, field="epoch")["status"] == "REJECTED"


def test_hvr_0924_field_type_is_strict() -> None:
    assert controller_field_type_receipt({"epoch": 1}, field="epoch", expected_type=int)["status"] == "PROVEN"
    assert controller_field_type_receipt({"epoch": True}, field="epoch", expected_type=int)["status"] == "REJECTED"


def test_hvr_0925_finite_value_is_required() -> None:
    assert controller_finite_receipt(1.25)["status"] == "PROVEN"
    assert controller_finite_receipt(float("inf"))["status"] == "REJECTED"


def test_hvr_0926_cutoff_boundary_is_inclusive() -> None:
    assert controller_cutoff_receipt(event_ts_ms=10, cutoff_ts_ms=10)["status"] == "PROVEN"
    assert controller_cutoff_receipt(event_ts_ms=11, cutoff_ts_ms=10)["status"] == "REJECTED"


def test_hvr_0927_old_event_is_rejected() -> None:
    assert controller_age_receipt(event_ts_ms=10, oldest_allowed_ts_ms=10)["status"] == "PROVEN"
    assert controller_age_receipt(event_ts_ms=9, oldest_allowed_ts_ms=10)["status"] == "REJECTED"


def test_hvr_0928_duplicate_events_are_rejected() -> None:
    assert controller_duplicate_receipt(event_ids=["a", "b"])["status"] == "PROVEN"
    assert controller_duplicate_receipt(event_ids=["a", "a"])["status"] == "REJECTED"


def test_hvr_0929_retry_requires_checkpoint() -> None:
    assert controller_retry_receipt(attempts=1, max_attempts=2, checkpoint_saved=True)["status"] == "PROVEN"
    assert controller_retry_receipt(attempts=3, max_attempts=2, checkpoint_saved=True)["status"] == "REJECTED"


def test_hvr_0930_replay_must_be_identical() -> None:
    assert controller_replay_receipt(outputs=[{"phase": "IDLE"}, {"phase": "IDLE"}])["status"] == "PROVEN"
    assert controller_replay_receipt(outputs=[{"phase": "IDLE"}, {"phase": "COLLECT"}])["status"] == "REJECTED"


def test_hvr_0931_analysis_requires_drain() -> None:
    assert controller_stage_order_receipt(phase="ANALYZE", analysis_stage="REPLAY", drained=True)["status"] == "PROVEN"
    assert controller_stage_order_receipt(phase="ANALYZE", analysis_stage="REPLAY", drained=False)["status"] == "REJECTED"


def test_hvr_0932_automatic_collect_requires_authorization() -> None:
    assert controller_collect_authorization_receipt(phase="COLLECT", automatic=True, authorized=True)["status"] == "PROVEN"
    assert controller_collect_authorization_receipt(phase="COLLECT", automatic=True, authorized=False)["status"] == "REJECTED"


def test_hvr_0933_request_replay_is_rejected() -> None:
    assert controller_request_replay_receipt(request_ids=["r1"], accepted_request_ids=["r1"])["status"] == "PROVEN"
    assert controller_request_replay_receipt(request_ids=["r1", "r1"], accepted_request_ids=["r1"])["status"] == "REJECTED"


def test_hvr_0934_epoch_must_be_current() -> None:
    assert controller_epoch_receipt(observed_epoch=4, current_epoch=4)["status"] == "PROVEN"
    assert controller_epoch_receipt(observed_epoch=3, current_epoch=4)["status"] == "REJECTED"


def test_hvr_0935_sha_must_match() -> None:
    digest = "a" * 64
    assert controller_hash_receipt(expected_sha=digest, actual_sha=digest)["status"] == "PROVEN"
    assert controller_hash_receipt(expected_sha=digest, actual_sha="b" * 64)["status"] == "REJECTED"


def test_hvr_0936_lease_requires_owner_and_time() -> None:
    assert controller_lease_receipt(worker_id="w1", lease_owner="w1", lease_expires_at_ms=20, now_ms=10)["status"] == "PROVEN"
    assert controller_lease_receipt(worker_id="w1", lease_owner="w2", lease_expires_at_ms=20, now_ms=10)["status"] == "REJECTED"


def test_hvr_0937_single_owner_blocks_split_brain() -> None:
    assert controller_single_owner_receipt(owner_ids=["w1"])["status"] == "PROVEN"
    assert controller_single_owner_receipt(owner_ids=["w1", "w2"])["status"] == "REJECTED"


def test_hvr_0938_checkpoint_must_be_complete() -> None:
    assert controller_checkpoint_receipt(checkpoint={"saved": True, "epoch": 4}, required_fields=["epoch"])["status"] == "PROVEN"
    assert controller_checkpoint_receipt(checkpoint={"saved": True}, required_fields=["epoch"])["status"] == "REJECTED"


def test_hvr_0939_self_hosted_runner_is_rejected() -> None:
    assert controller_runner_receipt(runner_label="ubuntu-latest")["status"] == "PROVEN"
    assert controller_runner_receipt(runner_label="self-hosted")["status"] == "REJECTED"


def test_hvr_0940_done_requires_coverage() -> None:
    assert controller_done_coverage_receipt(phase="ANALYZE", analysis_stage="DONE", coverage_status="PROVEN", required_proofs=["p1"], completed_proofs=["p1"])["status"] == "PROVEN"
    assert controller_done_coverage_receipt(phase="ANALYZE", analysis_stage="DONE", coverage_status="PROVEN", required_proofs=["p1"], completed_proofs=[])["status"] == "REJECTED"

