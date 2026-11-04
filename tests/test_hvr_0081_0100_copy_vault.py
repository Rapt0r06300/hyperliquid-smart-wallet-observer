"""Direct Bitget-to-paper-liquidity boundary tests for ASF-HVR-INT-0081..0100."""

from src.hl_observer.paper_trading.liquidity_consumption import (
    LiquidityConsumptionLedger,
    liquidity_consumption_safety_receipt,
    liquidity_quantity_receipt,
)
from src.hl_observer.venues.bitget import (
    bitget_truth_asset_receipt,
    bitget_truth_capacity_receipt,
    bitget_truth_checkpoint_receipt,
    bitget_truth_clock_receipt,
    bitget_truth_conflict_receipt,
    bitget_truth_done_receipt,
    bitget_truth_duplicate_receipt,
    bitget_truth_field_type_receipt,
    bitget_truth_finite_receipt,
    bitget_truth_fixture_receipt,
    bitget_truth_future_receipt,
    bitget_truth_gap_receipt,
    bitget_truth_lateness_receipt,
    bitget_truth_manifest_receipt,
    bitget_truth_null_field_receipt,
    bitget_truth_order_receipt,
    bitget_truth_overlap_receipt,
    bitget_truth_position_receipt,
    bitget_truth_required_field_receipt,
    bitget_truth_retry_receipt,
    bitget_truth_scope_receipt,
)


def _event(native_id: str = "evt-1", sequence: int = 1, payload_hash: str | None = None) -> dict:
    return {
        "native_id": native_id,
        "source": "bitget:ws:books",
        "sequence": sequence,
        "received_ts_ms": 3_010,
        "exchange_ts_ms": 3_000,
        "payload_hash": payload_hash or "a" * 64,
        "payload": {"symbol": "BTCUSDT", "bids": [[100.0, 1.0]], "asks": [[101.0, 1.0]]},
    }


def test_hvr_0081_bitget_fixture_reaches_paper_liquidity_once() -> None:
    assert bitget_truth_fixture_receipt(events=[_event()], causal_outputs=1)["status"] == "PROVEN"
    assert liquidity_consumption_safety_receipt(LiquidityConsumptionLedger())["status"] == "PROVEN"


def test_hvr_0082_missing_field_is_rejected() -> None:
    assert bitget_truth_required_field_receipt({}, field="native_id")["status"] == "REJECTED"


def test_hvr_0083_null_and_wrong_type_are_rejected() -> None:
    assert bitget_truth_null_field_receipt({"native_id": None}, field="native_id")["status"] == "REJECTED"
    assert bitget_truth_field_type_receipt({**_event(), "sequence": "1"}, field="sequence", expected_type=int)["status"] == "REJECTED"


def test_hvr_0084_non_finite_quantity_is_rejected() -> None:
    assert bitget_truth_finite_receipt(quantity=float("nan"))["status"] == "REJECTED"


def test_hvr_0085_late_timestamp_is_rejected() -> None:
    assert bitget_truth_lateness_receipt(exchange_ts_ms=3000, received_ts_ms=3010, max_delay_ms=20)["status"] == "PROVEN"
    assert bitget_truth_lateness_receipt(exchange_ts_ms=3000, received_ts_ms=3030, max_delay_ms=20)["status"] == "REJECTED"


def test_hvr_0086_future_event_is_rejected() -> None:
    assert bitget_truth_future_receipt(event_ts_ms=3000, decision_cutoff_ms=3000)["status"] == "PROVEN"
    assert bitget_truth_future_receipt(event_ts_ms=3001, decision_cutoff_ms=3000)["status"] == "REJECTED"


def test_hvr_0087_reversed_order_is_rejected() -> None:
    assert bitget_truth_order_receipt(sequences=[1, 2, 3])["status"] == "PROVEN"
    assert bitget_truth_order_receipt(sequences=[1, 3, 2])["status"] == "REJECTED"


def test_hvr_0088_duplicate_source_identity_is_rejected() -> None:
    assert bitget_truth_duplicate_receipt(event_ids=["a", "b"])["status"] == "PROVEN"
    assert bitget_truth_duplicate_receipt(event_ids=["a", "a"])["status"] == "REJECTED"


def test_hvr_0089_divergent_payload_is_quarantined() -> None:
    assert bitget_truth_conflict_receipt(events=[_event(), _event()])["status"] == "PROVEN"
    assert bitget_truth_conflict_receipt(events=[_event(), _event(payload_hash="b" * 64)])["status"] == "REJECTED"


def test_hvr_0090_overlap_is_not_double_counted() -> None:
    assert bitget_truth_overlap_receipt(first=[_event()], second=[_event()])["status"] == "PROVEN"
    assert bitget_truth_overlap_receipt(first=[_event()], second=[_event(payload_hash="b" * 64)])["status"] == "REJECTED"


def test_hvr_0091_sequence_gap_is_rejected() -> None:
    assert bitget_truth_gap_receipt(sequences=[1, 2, 3])["status"] == "PROVEN"
    assert bitget_truth_gap_receipt(sequences=[1, 3])["status"] == "REJECTED"


def test_hvr_0092_divergent_clocks_are_rejected() -> None:
    assert bitget_truth_clock_receipt(exchange_ts_ms=3000, received_ts_ms=3010, now_ms=3020)["status"] == "PROVEN"
    assert bitget_truth_clock_receipt(exchange_ts_ms=3010, received_ts_ms=3000, now_ms=3020)["status"] == "REJECTED"


def test_hvr_0093_retry_requires_recovery_checkpoint() -> None:
    assert bitget_truth_retry_receipt(attempts=1, max_attempts=2, recovered=True, checkpoint_saved=True)["status"] == "PROVEN"
    assert bitget_truth_retry_receipt(attempts=3, max_attempts=2, recovered=True, checkpoint_saved=True)["status"] == "REJECTED"


def test_hvr_0094_partial_checkpoint_is_rejected() -> None:
    assert bitget_truth_checkpoint_receipt(checkpoint={"saved": True, "sequence": 3}, required_fields=["sequence"])["status"] == "PROVEN"
    assert bitget_truth_checkpoint_receipt(checkpoint={"saved": True}, required_fields=["sequence"])["status"] == "REJECTED"


def test_hvr_0095_manifest_contradiction_is_rejected() -> None:
    digest = "a" * 64
    assert bitget_truth_manifest_receipt(expected_sha=digest, actual_sha=digest)["status"] == "PROVEN"
    assert bitget_truth_manifest_receipt(expected_sha=digest, actual_sha="b" * 64)["status"] == "REJECTED"


def test_hvr_0096_incomplete_asset_is_rejected() -> None:
    assert bitget_truth_asset_receipt(available=True, complete=True)["status"] == "PROVEN"
    assert bitget_truth_asset_receipt(available=True, complete=False)["status"] == "REJECTED"


def test_hvr_0097_missing_depth_cannot_cover_request() -> None:
    assert bitget_truth_capacity_receipt(requested_quantity=1.0, visible_depth=2.0)["status"] == "PROVEN"
    assert liquidity_quantity_receipt(requested_quantity=3.0, visible_depth=2.0)["status"] == "REJECTED"


def test_hvr_0098_missing_position_state_is_rejected() -> None:
    assert bitget_truth_position_receipt(fees=1.0, margin=100.0, mark=100.0)["status"] == "PROVEN"
    assert bitget_truth_position_receipt(fees=None, margin=100.0, mark=100.0)["status"] == "REJECTED"


def test_hvr_0099_scope_and_execution_are_blocked() -> None:
    assert bitget_truth_scope_receipt(family="Copy-Vault", execution_requested=False)["status"] == "PROVEN"
    assert bitget_truth_scope_receipt(family="Arbitrage", execution_requested=True)["status"] == "REJECTED"


def test_hvr_0100_done_without_proof_is_rejected() -> None:
    assert bitget_truth_done_receipt(status="PROVEN", coverage_status="PROVEN", proof_ids=["p1"], replay_verified=True)["status"] == "PROVEN"
    assert bitget_truth_done_receipt(status="PROVEN", coverage_status="PROVEN", proof_ids=[], replay_verified=True)["status"] == "REJECTED"
