"""Direct OKX and latency-truth boundary tests for HVR-0061..0080."""

from src.hl_observer.paper_trading.latency_truth import (
    latency_truth_asset_receipt,
    latency_truth_capacity_receipt,
    latency_truth_checkpoint_receipt,
    latency_truth_clock_receipt,
    latency_truth_conflict_receipt,
    latency_truth_done_receipt,
    latency_truth_duplicate_receipt,
    latency_truth_finite_receipt,
    latency_truth_fixture_receipt,
    latency_truth_future_receipt,
    latency_truth_gap_receipt,
    latency_truth_lateness_receipt,
    latency_truth_manifest_receipt,
    latency_truth_order_receipt,
    latency_truth_overlap_receipt,
    latency_truth_position_receipt,
    latency_truth_required_field_receipt,
    latency_truth_retry_receipt,
    latency_truth_scope_receipt,
)
from src.hl_observer.venues.okx import (
    okx_truth_asset_receipt,
    okx_truth_capacity_receipt,
    okx_truth_checkpoint_receipt,
    okx_truth_clock_receipt,
    okx_truth_conflict_receipt,
    okx_truth_done_receipt,
    okx_truth_duplicate_receipt,
    okx_truth_field_type_receipt,
    okx_truth_finite_receipt,
    okx_truth_fixture_receipt,
    okx_truth_future_receipt,
    okx_truth_gap_receipt,
    okx_truth_lateness_receipt,
    okx_truth_manifest_receipt,
    okx_truth_order_receipt,
    okx_truth_overlap_receipt,
    okx_truth_position_receipt,
    okx_truth_required_field_receipt,
    okx_truth_retry_receipt,
    okx_truth_scope_receipt,
)


def _event(native_id: str = "evt-1", sequence: int = 1, payload_hash: str | None = None) -> dict:
    return {
        "native_id": native_id,
        "source": "okx:ws:books",
        "sequence": sequence,
        "received_ts_ms": 3_010,
        "exchange_ts_ms": 3_000,
        "payload_hash": payload_hash or "a" * 64,
        "payload": {"instId": "BTC-USDT-SWAP", "bids": [[100.0, 1.0]], "asks": [[101.0, 1.0]]},
    }


def test_hvr_0061_okx_fixture_is_causal() -> None:
    assert okx_truth_fixture_receipt(events=[_event()], causal_outputs=1)["status"] == "PROVEN"
    assert okx_truth_fixture_receipt(events=[{**_event(), "payload": None}], causal_outputs=1)["status"] == "REJECTED"


def test_hvr_0062_okx_required_field_is_rejected_when_missing() -> None:
    assert okx_truth_required_field_receipt(_event(), field="native_id")["status"] == "PROVEN"
    assert okx_truth_required_field_receipt({}, field="native_id")["status"] == "REJECTED"


def test_hvr_0063_okx_field_type_is_strict() -> None:
    assert okx_truth_field_type_receipt(_event(), field="sequence", expected_type=int)["status"] == "PROVEN"
    assert okx_truth_field_type_receipt({**_event(), "sequence": "1"}, field="sequence", expected_type=int)["status"] == "REJECTED"


def test_hvr_0064_okx_quantity_is_finite_and_positive() -> None:
    assert okx_truth_finite_receipt(quantity=1.0)["status"] == "PROVEN"
    assert okx_truth_finite_receipt(quantity=float("inf"))["status"] == "REJECTED"


def test_hvr_0065_okx_lateness_is_bounded() -> None:
    assert okx_truth_lateness_receipt(exchange_ts_ms=3000, received_ts_ms=3010, max_delay_ms=20)["status"] == "PROVEN"
    assert okx_truth_lateness_receipt(exchange_ts_ms=3000, received_ts_ms=3030, max_delay_ms=20)["status"] == "REJECTED"


def test_hvr_0066_okx_future_event_is_rejected() -> None:
    assert okx_truth_future_receipt(event_ts_ms=3000, decision_cutoff_ms=3000)["status"] == "PROVEN"
    assert okx_truth_future_receipt(event_ts_ms=3001, decision_cutoff_ms=3000)["status"] == "REJECTED"


def test_hvr_0067_okx_sequence_order_is_monotonic() -> None:
    assert okx_truth_order_receipt(sequences=[1, 2, 3])["status"] == "PROVEN"
    assert okx_truth_order_receipt(sequences=[1, 3, 2])["status"] == "REJECTED"


def test_hvr_0068_okx_duplicate_identity_is_rejected() -> None:
    assert okx_truth_duplicate_receipt(native_ids=["a", "b"])["status"] == "PROVEN"
    assert okx_truth_duplicate_receipt(native_ids=["a", "a"])["status"] == "REJECTED"


def test_hvr_0069_okx_conflict_is_quarantined() -> None:
    assert okx_truth_conflict_receipt(events=[_event(), _event()])["status"] == "PROVEN"
    assert okx_truth_conflict_receipt(events=[_event(), _event(payload_hash="b" * 64)])["status"] == "REJECTED"


def test_hvr_0070_okx_overlap_is_deduplicable() -> None:
    assert okx_truth_overlap_receipt(first=[_event()], second=[_event()])["status"] == "PROVEN"
    assert okx_truth_overlap_receipt(first=[_event()], second=[_event(payload_hash="b" * 64)])["status"] == "REJECTED"


def test_hvr_0071_latency_truth_sequence_gap_is_rejected() -> None:
    assert latency_truth_gap_receipt(sequences=[1, 2, 3])["status"] == "PROVEN"
    assert latency_truth_gap_receipt(sequences=[1, 3])["status"] == "REJECTED"


def test_hvr_0072_latency_truth_clock_is_causal() -> None:
    assert latency_truth_clock_receipt(exchange_ts_ms=3000, received_ts_ms=3010, now_ms=3020)["status"] == "PROVEN"
    assert latency_truth_clock_receipt(exchange_ts_ms=3010, received_ts_ms=3000, now_ms=3020)["status"] == "REJECTED"


def test_hvr_0073_latency_truth_retry_requires_checkpoint() -> None:
    assert latency_truth_retry_receipt(attempts=1, max_attempts=2, checkpoint_saved=True)["status"] == "PROVEN"
    assert latency_truth_retry_receipt(attempts=3, max_attempts=2, checkpoint_saved=True)["status"] == "REJECTED"


def test_hvr_0074_latency_truth_checkpoint_is_complete() -> None:
    assert latency_truth_checkpoint_receipt(checkpoint={"saved": True, "sequence": 3}, required_fields=["sequence"])["status"] == "PROVEN"
    assert latency_truth_checkpoint_receipt(checkpoint={"saved": True}, required_fields=["sequence"])["status"] == "REJECTED"


def test_hvr_0075_latency_truth_manifest_must_match() -> None:
    digest = "a" * 64
    assert latency_truth_manifest_receipt(expected_sha=digest, actual_sha=digest)["status"] == "PROVEN"
    assert latency_truth_manifest_receipt(expected_sha=digest, actual_sha="b" * 64)["status"] == "REJECTED"


def test_hvr_0076_latency_truth_asset_must_be_complete() -> None:
    assert latency_truth_asset_receipt(available=True, complete=True)["status"] == "PROVEN"
    assert latency_truth_asset_receipt(available=True, complete=False)["status"] == "REJECTED"


def test_hvr_0077_latency_truth_capacity_covers_request() -> None:
    assert latency_truth_capacity_receipt(requested_quantity=1.0, visible_depth=2.0)["status"] == "PROVEN"
    assert latency_truth_capacity_receipt(requested_quantity=3.0, visible_depth=2.0)["status"] == "REJECTED"


def test_hvr_0078_latency_truth_position_costs_are_required() -> None:
    assert latency_truth_position_receipt(fees=1.0, margin=100.0, mark=100.0)["status"] == "PROVEN"
    assert latency_truth_position_receipt(fees=None, margin=100.0, mark=100.0)["status"] == "REJECTED"


def test_hvr_0079_latency_truth_scope_blocks_execution() -> None:
    assert latency_truth_scope_receipt(family="Copy-Vault", execution_requested=False)["status"] == "PROVEN"
    assert latency_truth_scope_receipt(family="Arbitrage", execution_requested=True)["status"] == "REJECTED"


def test_hvr_0080_latency_truth_done_requires_replay_coverage() -> None:
    assert latency_truth_done_receipt(status="PROVEN", coverage_status="PROVEN", proof_ids=["p1"], replay_verified=True)["status"] == "PROVEN"
    assert latency_truth_done_receipt(status="PROVEN", coverage_status="PROVEN", proof_ids=[], replay_verified=True)["status"] == "REJECTED"
