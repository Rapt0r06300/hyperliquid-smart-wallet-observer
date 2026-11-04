"""Fail-closed native-feed to L2 boundary controls for ASF-HVR-INT-0001..0020."""

from hl_observer.market_data.live_l2_service import (
    native_l2_asset_receipt,
    native_l2_capacity_receipt,
    native_l2_checkpoint_receipt,
    native_l2_clock_receipt,
    native_l2_conflict_receipt,
    native_l2_done_receipt,
    native_l2_duplicate_receipt,
    native_l2_field_type_receipt,
    native_l2_finite_receipt,
    native_l2_fixture_receipt,
    native_l2_future_receipt,
    native_l2_gap_receipt,
    native_l2_lateness_receipt,
    native_l2_manifest_receipt,
    native_l2_overlap_receipt,
    native_l2_order_receipt,
    native_l2_position_receipt,
    native_l2_required_field_receipt,
    native_l2_retry_receipt,
    native_l2_scope_receipt,
)


def _event(native_id: str = "evt-1", sequence: int = 1, payload_hash: str | None = None) -> dict:
    return {
        "native_id": native_id,
        "source": "hyperliquid:ws:l2Book",
        "sequence": sequence,
        "received_ts_ms": 1_010,
        "exchange_ts_ms": 1_000,
        "payload_hash": payload_hash or "a" * 64,
        "payload": {"coin": "BTC", "bids": [[100.0, 1.0]], "asks": [[101.0, 1.0]]},
    }


def test_asf_hvr_int_0001_native_fixture_is_causal() -> None:
    assert native_l2_fixture_receipt(events=[_event()], causal_outputs=1)["status"] == "PROVEN"
    assert native_l2_fixture_receipt(events=[{**_event(), "source": ""}], causal_outputs=1)["status"] == "REJECTED"


def test_asf_hvr_int_0002_required_field_is_rejected_when_absent() -> None:
    assert native_l2_required_field_receipt(_event(), field="native_id")["status"] == "PROVEN"
    assert native_l2_required_field_receipt({"source": "ws"}, field="native_id")["status"] == "REJECTED"


def test_asf_hvr_int_0003_field_type_is_strict() -> None:
    assert native_l2_field_type_receipt(_event(), field="sequence", expected_type=int)["status"] == "PROVEN"
    assert native_l2_field_type_receipt({**_event(), "sequence": "1"}, field="sequence", expected_type=int)["status"] == "REJECTED"


def test_asf_hvr_int_0004_quantity_must_be_finite_and_positive() -> None:
    assert native_l2_finite_receipt(quantity=1.0)["status"] == "PROVEN"
    assert native_l2_finite_receipt(quantity=float("nan"))["status"] == "REJECTED"


def test_asf_hvr_int_0005_late_timestamp_is_rejected() -> None:
    assert native_l2_lateness_receipt(exchange_ts_ms=1000, received_ts_ms=1010, max_delay_ms=20)["status"] == "PROVEN"
    assert native_l2_lateness_receipt(exchange_ts_ms=1000, received_ts_ms=1030, max_delay_ms=20)["status"] == "REJECTED"


def test_asf_hvr_int_0006_future_event_is_rejected() -> None:
    assert native_l2_future_receipt(event_ts_ms=1000, decision_cutoff_ms=1000)["status"] == "PROVEN"
    assert native_l2_future_receipt(event_ts_ms=1001, decision_cutoff_ms=1000)["status"] == "REJECTED"


def test_asf_hvr_int_0007_event_order_is_monotonic() -> None:
    assert native_l2_order_receipt(sequences=[1, 2, 3])["status"] == "PROVEN"
    assert native_l2_order_receipt(sequences=[1, 3, 2])["status"] == "REJECTED"


def test_asf_hvr_int_0008_duplicate_identity_is_rejected() -> None:
    assert native_l2_duplicate_receipt(native_ids=["a", "b"])["status"] == "PROVEN"
    assert native_l2_duplicate_receipt(native_ids=["a", "a"])["status"] == "REJECTED"


def test_asf_hvr_int_0009_conflicting_payload_is_quarantined() -> None:
    assert native_l2_conflict_receipt(events=[_event(), _event(payload_hash="a" * 64)])["status"] == "PROVEN"
    assert native_l2_conflict_receipt(events=[_event(), _event(payload_hash="b" * 64)])["status"] == "REJECTED"


def test_asf_hvr_int_0010_overlap_is_deduplicable_only_when_identical() -> None:
    assert native_l2_overlap_receipt(first=[_event()], second=[_event()])["status"] == "PROVEN"
    assert native_l2_overlap_receipt(first=[_event()], second=[_event(payload_hash="b" * 64)])["status"] == "REJECTED"


def test_asf_hvr_int_0011_sequence_gap_is_rejected() -> None:
    assert native_l2_gap_receipt(sequences=[1, 2, 3])["status"] == "PROVEN"
    assert native_l2_gap_receipt(sequences=[1, 3])["status"] == "REJECTED"


def test_asf_hvr_int_0012_clock_order_is_causal() -> None:
    assert native_l2_clock_receipt(exchange_ts_ms=1000, received_ts_ms=1010, now_ms=1020)["status"] == "PROVEN"
    assert native_l2_clock_receipt(exchange_ts_ms=1010, received_ts_ms=1000, now_ms=1020)["status"] == "REJECTED"


def test_asf_hvr_int_0013_retry_requires_checkpoint() -> None:
    assert native_l2_retry_receipt(attempts=1, max_attempts=2, checkpoint_saved=True)["status"] == "PROVEN"
    assert native_l2_retry_receipt(attempts=3, max_attempts=2, checkpoint_saved=True)["status"] == "REJECTED"


def test_asf_hvr_int_0014_checkpoint_must_be_complete() -> None:
    assert native_l2_checkpoint_receipt(checkpoint={"saved": True, "sequence": 3}, required_fields=["sequence"])["status"] == "PROVEN"
    assert native_l2_checkpoint_receipt(checkpoint={"saved": True}, required_fields=["sequence"])["status"] == "REJECTED"


def test_asf_hvr_int_0015_manifest_must_match() -> None:
    digest = "a" * 64
    assert native_l2_manifest_receipt(expected_sha=digest, actual_sha=digest)["status"] == "PROVEN"
    assert native_l2_manifest_receipt(expected_sha=digest, actual_sha="b" * 64)["status"] == "REJECTED"


def test_asf_hvr_int_0016_incomplete_asset_is_rejected() -> None:
    assert native_l2_asset_receipt(available=True, complete=True)["status"] == "PROVEN"
    assert native_l2_asset_receipt(available=True, complete=False)["status"] == "REJECTED"


def test_asf_hvr_int_0017_capacity_must_cover_request() -> None:
    assert native_l2_capacity_receipt(requested_quantity=1.0, visible_depth=2.0)["status"] == "PROVEN"
    assert native_l2_capacity_receipt(requested_quantity=3.0, visible_depth=2.0)["status"] == "REJECTED"


def test_asf_hvr_int_0018_position_costs_are_required() -> None:
    assert native_l2_position_receipt(fees=1.0, margin=100.0, mark=100.0)["status"] == "PROVEN"
    assert native_l2_position_receipt(fees=None, margin=100.0, mark=100.0)["status"] == "REJECTED"


def test_asf_hvr_int_0019_scope_blocks_execution() -> None:
    assert native_l2_scope_receipt(family="Copy-Vault", execution_requested=False)["status"] == "PROVEN"
    assert native_l2_scope_receipt(family="Arbitrage", execution_requested=True)["status"] == "REJECTED"


def test_asf_hvr_int_0020_done_requires_replay_coverage() -> None:
    assert native_l2_done_receipt(status="PROVEN", coverage_status="PROVEN", proof_ids=["p1"], replay_verified=True)["status"] == "PROVEN"
    assert native_l2_done_receipt(status="PROVEN", coverage_status="PROVEN", proof_ids=[], replay_verified=True)["status"] == "REJECTED"
