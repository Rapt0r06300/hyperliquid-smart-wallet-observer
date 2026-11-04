"""Fail-closed Binance-to-Gate boundary controls for ASF-HVR-INT-0021..0040."""

from src.hl_observer.venues.binance import (
    binance_gate_asset_receipt,
    binance_gate_capacity_receipt,
    binance_gate_checkpoint_receipt,
    binance_gate_clock_receipt,
    binance_gate_conflict_receipt,
    binance_gate_done_receipt,
    binance_gate_duplicate_receipt,
    binance_gate_field_type_receipt,
    binance_gate_finite_receipt,
    binance_gate_fixture_receipt,
    binance_gate_future_receipt,
    binance_gate_gap_receipt,
    binance_gate_lateness_receipt,
    binance_gate_manifest_receipt,
    binance_gate_overlap_receipt,
    binance_gate_order_receipt,
    binance_gate_position_receipt,
    binance_gate_required_field_receipt,
    binance_gate_retry_receipt,
    binance_gate_scope_receipt,
)


def _event(native_id: str = "evt-1", sequence: int = 1, payload_hash: str | None = None) -> dict:
    return {
        "native_id": native_id,
        "source": "binance:ws:depth",
        "sequence": sequence,
        "received_ts_ms": 2_010,
        "exchange_ts_ms": 2_000,
        "payload_hash": payload_hash or "a" * 64,
        "payload": {"symbol": "BTCUSDT", "bids": [[100.0, 1.0]], "asks": [[101.0, 1.0]]},
    }


def test_asf_hvr_int_0021_binance_gate_fixture_is_causal() -> None:
    assert binance_gate_fixture_receipt(events=[_event()], causal_outputs=1)["status"] == "PROVEN"
    assert binance_gate_fixture_receipt(events=[{**_event(), "payload": None}], causal_outputs=1)["status"] == "REJECTED"


def test_asf_hvr_int_0022_required_field_is_rejected() -> None:
    assert binance_gate_required_field_receipt(_event(), field="native_id")["status"] == "PROVEN"
    assert binance_gate_required_field_receipt({}, field="native_id")["status"] == "REJECTED"


def test_asf_hvr_int_0023_field_type_is_strict() -> None:
    assert binance_gate_field_type_receipt(_event(), field="sequence", expected_type=int)["status"] == "PROVEN"
    assert binance_gate_field_type_receipt({**_event(), "sequence": "1"}, field="sequence", expected_type=int)["status"] == "REJECTED"


def test_asf_hvr_int_0024_quantity_is_finite() -> None:
    assert binance_gate_finite_receipt(quantity=1.0)["status"] == "PROVEN"
    assert binance_gate_finite_receipt(quantity=float("inf"))["status"] == "REJECTED"


def test_asf_hvr_int_0025_lateness_is_bounded() -> None:
    assert binance_gate_lateness_receipt(exchange_ts_ms=2000, received_ts_ms=2010, max_delay_ms=20)["status"] == "PROVEN"
    assert binance_gate_lateness_receipt(exchange_ts_ms=2000, received_ts_ms=2030, max_delay_ms=20)["status"] == "REJECTED"


def test_asf_hvr_int_0026_future_event_is_rejected() -> None:
    assert binance_gate_future_receipt(event_ts_ms=2000, decision_cutoff_ms=2000)["status"] == "PROVEN"
    assert binance_gate_future_receipt(event_ts_ms=2001, decision_cutoff_ms=2000)["status"] == "REJECTED"


def test_asf_hvr_int_0027_event_order_is_monotonic() -> None:
    assert binance_gate_order_receipt(sequences=[1, 2, 3])["status"] == "PROVEN"
    assert binance_gate_order_receipt(sequences=[1, 3, 2])["status"] == "REJECTED"


def test_asf_hvr_int_0028_duplicate_identity_is_rejected() -> None:
    assert binance_gate_duplicate_receipt(native_ids=["a", "b"])["status"] == "PROVEN"
    assert binance_gate_duplicate_receipt(native_ids=["a", "a"])["status"] == "REJECTED"


def test_asf_hvr_int_0029_conflict_is_quarantined() -> None:
    assert binance_gate_conflict_receipt(events=[_event(), _event(payload_hash="a" * 64)])["status"] == "PROVEN"
    assert binance_gate_conflict_receipt(events=[_event(), _event(payload_hash="b" * 64)])["status"] == "REJECTED"


def test_asf_hvr_int_0030_overlap_is_deduplicable() -> None:
    assert binance_gate_overlap_receipt(first=[_event()], second=[_event()])["status"] == "PROVEN"
    assert binance_gate_overlap_receipt(first=[_event()], second=[_event(payload_hash="b" * 64)])["status"] == "REJECTED"


def test_asf_hvr_int_0031_sequence_gap_is_rejected() -> None:
    assert binance_gate_gap_receipt(sequences=[1, 2, 3])["status"] == "PROVEN"
    assert binance_gate_gap_receipt(sequences=[1, 3])["status"] == "REJECTED"


def test_asf_hvr_int_0032_clock_order_is_causal() -> None:
    assert binance_gate_clock_receipt(exchange_ts_ms=2000, received_ts_ms=2010, now_ms=2020)["status"] == "PROVEN"
    assert binance_gate_clock_receipt(exchange_ts_ms=2010, received_ts_ms=2000, now_ms=2020)["status"] == "REJECTED"


def test_asf_hvr_int_0033_retry_requires_checkpoint() -> None:
    assert binance_gate_retry_receipt(attempts=1, max_attempts=2, checkpoint_saved=True)["status"] == "PROVEN"
    assert binance_gate_retry_receipt(attempts=3, max_attempts=2, checkpoint_saved=True)["status"] == "REJECTED"


def test_asf_hvr_int_0034_checkpoint_must_be_complete() -> None:
    assert binance_gate_checkpoint_receipt(checkpoint={"saved": True, "sequence": 3}, required_fields=["sequence"])["status"] == "PROVEN"
    assert binance_gate_checkpoint_receipt(checkpoint={"saved": True}, required_fields=["sequence"])["status"] == "REJECTED"


def test_asf_hvr_int_0035_manifest_must_match() -> None:
    digest = "a" * 64
    assert binance_gate_manifest_receipt(expected_sha=digest, actual_sha=digest)["status"] == "PROVEN"
    assert binance_gate_manifest_receipt(expected_sha=digest, actual_sha="b" * 64)["status"] == "REJECTED"


def test_asf_hvr_int_0036_incomplete_asset_is_rejected() -> None:
    assert binance_gate_asset_receipt(available=True, complete=True)["status"] == "PROVEN"
    assert binance_gate_asset_receipt(available=True, complete=False)["status"] == "REJECTED"


def test_asf_hvr_int_0037_capacity_must_cover_request() -> None:
    assert binance_gate_capacity_receipt(requested_quantity=1.0, visible_depth=2.0)["status"] == "PROVEN"
    assert binance_gate_capacity_receipt(requested_quantity=3.0, visible_depth=2.0)["status"] == "REJECTED"


def test_asf_hvr_int_0038_position_costs_are_required() -> None:
    assert binance_gate_position_receipt(fees=1.0, margin=100.0, mark=100.0)["status"] == "PROVEN"
    assert binance_gate_position_receipt(fees=None, margin=100.0, mark=100.0)["status"] == "REJECTED"


def test_asf_hvr_int_0039_scope_blocks_execution() -> None:
    assert binance_gate_scope_receipt(family="Copy-Vault", execution_requested=False)["status"] == "PROVEN"
    assert binance_gate_scope_receipt(family="Arbitrage", execution_requested=True)["status"] == "REJECTED"


def test_asf_hvr_int_0040_done_requires_replay_coverage() -> None:
    assert binance_gate_done_receipt(status="PROVEN", coverage_status="PROVEN", proof_ids=["p1"], replay_verified=True)["status"] == "PROVEN"
    assert binance_gate_done_receipt(status="PROVEN", coverage_status="PROVEN", proof_ids=[], replay_verified=True)["status"] == "REJECTED"
