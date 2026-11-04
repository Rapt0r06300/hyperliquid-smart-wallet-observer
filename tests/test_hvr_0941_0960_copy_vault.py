"""Fail-closed resumable-campaign controls for HVR-0941..HVR-0960."""

from datetime import datetime, timedelta, timezone

from hl_observer.control_plane.resumable_campaign import (
    SCHEMA_VERSION_V2,
    CampaignManifest,
    campaign_age_receipt,
    campaign_checkpoint_receipt,
    campaign_collect_authorization_receipt,
    campaign_cutoff_receipt,
    campaign_done_coverage_receipt,
    campaign_duplicate_receipt,
    campaign_epoch_receipt,
    campaign_field_type_receipt,
    campaign_finite_receipt,
    campaign_hash_receipt,
    campaign_lease_receipt,
    campaign_null_field_receipt,
    campaign_replay_receipt,
    campaign_request_replay_receipt,
    campaign_required_field_receipt,
    campaign_retry_receipt,
    campaign_runner_receipt,
    campaign_single_owner_receipt,
    campaign_stage_order_receipt,
    campaign_state_safety_receipt,
)


def _manifest() -> CampaignManifest:
    now = datetime.now(timezone.utc)
    return CampaignManifest(
        "c1",
        "market_collection",
        "Rapt0r06300/hyperliquid-smart-wallet-observer",
        "a" * 40,
        "Rapt0r06300/hyperliquid-smart-wallet-observer",
        "g1",
        "b" * 64,
        "c" * 64,
        (now + timedelta(days=1)).isoformat(),
        schema_version=SCHEMA_VERSION_V2,
        created_at=now.isoformat(),
        creation_phase="COLLECT",
        phase_epoch=1,
    )


def test_hvr_0941_campaign_state_positive_and_hostile() -> None:
    assert campaign_state_safety_receipt(_manifest())["status"] == "PROVEN"
    assert campaign_state_safety_receipt({"status": "RUNNING"})["status"] == "REJECTED"


def test_hvr_0942_required_field_is_fail_closed() -> None:
    assert campaign_required_field_receipt({"epoch": 1}, field="epoch")["status"] == "PROVEN"
    assert campaign_required_field_receipt({}, field="epoch")["status"] == "REJECTED"


def test_hvr_0943_null_field_is_fail_closed() -> None:
    assert campaign_null_field_receipt({"epoch": 1}, field="epoch")["status"] == "PROVEN"
    assert campaign_null_field_receipt({"epoch": None}, field="epoch")["status"] == "REJECTED"


def test_hvr_0944_field_type_is_strict() -> None:
    assert campaign_field_type_receipt({"epoch": 1}, field="epoch", expected_type=int)["status"] == "PROVEN"
    assert campaign_field_type_receipt({"epoch": True}, field="epoch", expected_type=int)["status"] == "REJECTED"


def test_hvr_0945_finite_value_is_required() -> None:
    assert campaign_finite_receipt(1.25)["status"] == "PROVEN"
    assert campaign_finite_receipt(float("inf"))["status"] == "REJECTED"


def test_hvr_0946_cutoff_boundary_is_inclusive() -> None:
    assert campaign_cutoff_receipt(event_ts_ms=10, cutoff_ts_ms=10)["status"] == "PROVEN"
    assert campaign_cutoff_receipt(event_ts_ms=11, cutoff_ts_ms=10)["status"] == "REJECTED"


def test_hvr_0947_old_event_is_rejected() -> None:
    assert campaign_age_receipt(event_ts_ms=10, oldest_allowed_ts_ms=10)["status"] == "PROVEN"
    assert campaign_age_receipt(event_ts_ms=9, oldest_allowed_ts_ms=10)["status"] == "REJECTED"


def test_hvr_0948_duplicate_events_are_rejected() -> None:
    assert campaign_duplicate_receipt(event_ids=["a", "b"])["status"] == "PROVEN"
    assert campaign_duplicate_receipt(event_ids=["a", "a"])["status"] == "REJECTED"


def test_hvr_0949_retry_requires_checkpoint() -> None:
    assert campaign_retry_receipt(attempts=1, max_attempts=2, checkpoint_saved=True)["status"] == "PROVEN"
    assert campaign_retry_receipt(attempts=3, max_attempts=2, checkpoint_saved=True)["status"] == "REJECTED"


def test_hvr_0950_replay_must_be_identical() -> None:
    assert campaign_replay_receipt(outputs=[{"status": "RUNNING"}, {"status": "RUNNING"}])["status"] == "PROVEN"
    assert campaign_replay_receipt(outputs=[{"status": "RUNNING"}, {"status": "FAILED"}])["status"] == "REJECTED"


def test_hvr_0951_analysis_requires_drain() -> None:
    assert campaign_stage_order_receipt(creation_phase="ANALYZE", analysis_stage="REPLAY", drained=True)["status"] == "PROVEN"
    assert campaign_stage_order_receipt(creation_phase="ANALYZE", analysis_stage="REPLAY", drained=False)["status"] == "REJECTED"


def test_hvr_0952_automatic_collect_requires_authorization() -> None:
    assert campaign_collect_authorization_receipt(kind="market_collection", automatic=True, authorized=True)["status"] == "PROVEN"
    assert campaign_collect_authorization_receipt(kind="market_collection", automatic=True, authorized=False)["status"] == "REJECTED"


def test_hvr_0953_request_replay_is_rejected() -> None:
    assert campaign_request_replay_receipt(request_ids=["r1"], accepted_request_ids=["r1"])["status"] == "PROVEN"
    assert campaign_request_replay_receipt(request_ids=["r1", "r1"], accepted_request_ids=["r1"])["status"] == "REJECTED"


def test_hvr_0954_epoch_must_be_current() -> None:
    assert campaign_epoch_receipt(observed_epoch=4, current_epoch=4)["status"] == "PROVEN"
    assert campaign_epoch_receipt(observed_epoch=3, current_epoch=4)["status"] == "REJECTED"


def test_hvr_0955_sha_must_match() -> None:
    digest = "a" * 64
    assert campaign_hash_receipt(expected_sha=digest, actual_sha=digest)["status"] == "PROVEN"
    assert campaign_hash_receipt(expected_sha=digest, actual_sha="b" * 64)["status"] == "REJECTED"


def test_hvr_0956_lease_requires_owner_and_time() -> None:
    assert campaign_lease_receipt(worker_id="w1", lease_owner="w1", lease_expires_at_ms=20, now_ms=10)["status"] == "PROVEN"
    assert campaign_lease_receipt(worker_id="w1", lease_owner="w2", lease_expires_at_ms=20, now_ms=10)["status"] == "REJECTED"


def test_hvr_0957_single_owner_blocks_split_brain() -> None:
    assert campaign_single_owner_receipt(owner_ids=["w1"])["status"] == "PROVEN"
    assert campaign_single_owner_receipt(owner_ids=["w1", "w2"])["status"] == "REJECTED"


def test_hvr_0958_checkpoint_must_be_complete() -> None:
    assert campaign_checkpoint_receipt(checkpoint={"saved": True, "epoch": 4}, required_fields=["epoch"])["status"] == "PROVEN"
    assert campaign_checkpoint_receipt(checkpoint={"saved": True}, required_fields=["epoch"])["status"] == "REJECTED"


def test_hvr_0959_self_hosted_runner_is_rejected() -> None:
    assert campaign_runner_receipt(runner_label="ubuntu-latest")["status"] == "PROVEN"
    assert campaign_runner_receipt(runner_label="self-hosted")["status"] == "REJECTED"


def test_hvr_0960_done_requires_coverage() -> None:
    assert campaign_done_coverage_receipt(status="COMPLETE", coverage_status="PROVEN", required_proofs=["p1"], completed_proofs=["p1"])["status"] == "PROVEN"
    assert campaign_done_coverage_receipt(status="COMPLETE", coverage_status="PROVEN", required_proofs=["p1"], completed_proofs=[])["status"] == "REJECTED"

