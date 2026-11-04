"""Fail-closed Bybit-to-execution-truth boundary controls for ASF-HVR-INT-0041..0060."""

from src.hl_observer.venues.bybit import (
    bybit_truth_asset_receipt,
    bybit_truth_capacity_receipt,
    bybit_truth_checkpoint_receipt,
    bybit_truth_clock_receipt,
    bybit_truth_conflict_receipt,
    bybit_truth_done_receipt,
    bybit_truth_duplicate_receipt,
    bybit_truth_field_type_receipt,
    bybit_truth_finite_receipt,
    bybit_truth_fixture_receipt,
    bybit_truth_future_receipt,
    bybit_truth_gap_receipt,
    bybit_truth_lateness_receipt,
    bybit_truth_manifest_receipt,
    bybit_truth_overlap_receipt,
    bybit_truth_order_receipt,
    bybit_truth_position_receipt,
    bybit_truth_required_field_receipt,
    bybit_truth_retry_receipt,
    bybit_truth_scope_receipt,
)


def _event(native_id: str = "evt-1", sequence: int = 1, payload_hash: str | None = None) -> dict:
    return {
        "native_id": native_id,
        "source": "bybit:ws:orderbook",
        "sequence": sequence,
        "received_ts_ms": 3_010,
        "exchange_ts_ms": 3_000,
        "payload_hash": payload_hash or "a" * 64,
        "payload": {"symbol": "BTCUSDT", "bids": [[100.0, 1.0]], "asks": [[101.0, 1.0]]},
    }


def test_asf_hvr_int_0041_fixture_is_causal() -> None:
    assert bybit_truth_fixture_receipt(events=[_event()], causal_outputs=1)["status"] == "PROVEN"
    assert bybit_truth_fixture_receipt(events=[{**_event(), "payload": None}], causal_outputs=1)["status"] == "REJECTED"


def test_asf_hvr_int_0042_required_field_is_rejected() -> None:
    assert bybit_truth_required_field_receipt(_event(), field="native_id")["status"] == "PROVEN"
    assert bybit_truth_required_field_receipt({}, field="native_id")["status"] == "REJECTED"


def test_asf_hvr_int_0043_field_type_is_strict() -> None:
    assert bybit_truth_field_type_receipt(_event(), field="sequence", expected_type=int)["status"] == "PROVEN"
    assert bybit_truth_field_type_receipt({**_event(), "sequence": "1"}, field="sequence", expected_type=int)["status"] == "REJECTED"


def test_asf_hvr_int_0044_quantity_is_finite() -> None:
    assert bybit_truth_finite_receipt(quantity=1.0)["status"] == "PROVEN"
    assert bybit_truth_finite_receipt(quantity=float("inf"))["status"] == "REJECTED"


def test_asf_hvr_int_0045_lateness_is_bounded() -> None:
    assert bybit_truth_lateness_receipt(exchange_ts_ms=3000, received_ts_ms=3010, max_delay_ms=20)["status"] == "PROVEN"
    assert bybit_truth_lateness_receipt(exchange_ts_ms=3000, received_ts_ms=3030, max_delay_ms=20)["status"] == "REJECTED"


def test_asf_hvr_int_0046_future_event_is_rejected() -> None:
    assert bybit_truth_future_receipt(event_ts_ms=3000, decision_cutoff_ms=3000)["status"] == "PROVEN"
    assert bybit_truth_future_receipt(event_ts_ms=3001, decision_cutoff_ms=3000)["status"] == "REJECTED"


def test_asf_hvr_int_0047_order_is_monotonic() -> None:
    assert bybit_truth_order_receipt(sequences=[1, 2, 3])["status"] == "PROVEN"
    assert bybit_truth_order_receipt(sequences=[1, 3, 2])["status"] == "REJECTED"


def test_asf_hvr_int_0048_duplicate_identity_is_rejected() -> None:
    assert bybit_truth_duplicate_receipt(native_ids=["a", "b"])["status"] == "PROVEN"
    assert bybit_truth_duplicate_receipt(native_ids=["a", "a"])["status"] == "REJECTED"


def test_asf_hvr_int_0049_conflict_is_quarantined() -> None:
    assert bybit_truth_conflict_receipt(events=[_event(), _event(payload_hash="a" * 64)])["status"] == "PROVEN"
    assert bybit_truth_conflict_receipt(events=[_event(), _event(payload_hash="b" * 64)])["status"] == "REJECTED"


def test_asf_hvr_int_0050_overlap_is_deduplicable() -> None:
    assert bybit_truth_overlap_receipt(first=[_event()], second=[_event()])["status"] == "PROVEN"
    assert bybit_truth_overlap_receipt(first=[_event()], second=[_event(payload_hash="b" * 64)])["status"] == "REJECTED"


def test_asf_hvr_int_0051_sequence_gap_is_rejected() -> None:
    assert bybit_truth_gap_receipt(sequences=[1, 2, 3])["status"] == "PROVEN"
    assert bybit_truth_gap_receipt(sequences=[1, 3])["status"] == "REJECTED"


def test_asf_hvr_int_0052_clock_order_is_causal() -> None:
    assert bybit_truth_clock_receipt(exchange_ts_ms=3000, received_ts_ms=3010, now_ms=3020)["status"] == "PROVEN"
    assert bybit_truth_clock_receipt(exchange_ts_ms=3010, received_ts_ms=3000, now_ms=3020)["status"] == "REJECTED"


def test_asf_hvr_int_0053_retry_requires_checkpoint() -> None:
    assert bybit_truth_retry_receipt(attempts=1, max_attempts=2, checkpoint_saved=True)["status"] == "PROVEN"
    assert bybit_truth_retry_receipt(attempts=3, max_attempts=2, checkpoint_saved=True)["status"] == "REJECTED"


def test_asf_hvr_int_0054_checkpoint_must_be_complete() -> None:
    assert bybit_truth_checkpoint_receipt(checkpoint={"saved": True, "sequence": 3}, required_fields=["sequence"])["status"] == "PROVEN"
    assert bybit_truth_checkpoint_receipt(checkpoint={"saved": True}, required_fields=["sequence"])["status"] == "REJECTED"


def test_asf_hvr_int_0055_manifest_must_match() -> None:
    digest = "a" * 64
    assert bybit_truth_manifest_receipt(expected_sha=digest, actual_sha=digest)["status"] == "PROVEN"
    assert bybit_truth_manifest_receipt(expected_sha=digest, actual_sha="b" * 64)["status"] == "REJECTED"


def test_asf_hvr_int_0056_incomplete_asset_is_rejected() -> None:
    assert bybit_truth_asset_receipt(available=True, complete=True)["status"] == "PROVEN"
    assert bybit_truth_asset_receipt(available=True, complete=False)["status"] == "REJECTED"


def test_asf_hvr_int_0057_capacity_must_cover_request() -> None:
    assert bybit_truth_capacity_receipt(requested_quantity=1.0, visible_depth=2.0)["status"] == "PROVEN"
    assert bybit_truth_capacity_receipt(requested_quantity=3.0, visible_depth=2.0)["status"] == "REJECTED"


def test_asf_hvr_int_0058_position_costs_are_required() -> None:
    assert bybit_truth_position_receipt(fees=1.0, margin=100.0, mark=100.0)["status"] == "PROVEN"
    assert bybit_truth_position_receipt(fees=None, margin=100.0, mark=100.0)["status"] == "REJECTED"


def test_asf_hvr_int_0059_scope_blocks_execution() -> None:
    assert bybit_truth_scope_receipt(family="Copy-Vault", execution_requested=False)["status"] == "PROVEN"
    assert bybit_truth_scope_receipt(family="Arbitrage", execution_requested=True)["status"] == "REJECTED"


def test_asf_hvr_int_0060_done_requires_replay_coverage() -> None:
    assert bybit_truth_done_receipt(status="PROVEN", coverage_status="PROVEN", proof_ids=["p1"], replay_verified=True)["status"] == "PROVEN"
    assert bybit_truth_done_receipt(status="PROVEN", coverage_status="PROVEN", proof_ids=[], replay_verified=True)["status"] == "REJECTED"
