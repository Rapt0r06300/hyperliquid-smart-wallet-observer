import hashlib

from hl_observer.venues.copy_vault_stream_controls import (
    age_boundary_receipt, checksum_receipt, cutoff_boundary_receipt,
    delta_before_snapshot_receipt, duplicate_event_receipt,
    engine_timestamp_receipt, finite_field_receipt,
    instrument_mapping_receipt, l2_trade_consistency_receipt,
    native_event_contract_receipt, native_payload_hash_receipt,
    pagination_complete_receipt, rate_limit_retry_receipt,
    reconnect_repair_receipt, replay_determinism_receipt,
    required_field_receipt, retry_recovery_receipt,
    sequence_reset_receipt, snapshot_delta_order_receipt,
)


def test_hvr_0001_native_event_contract():
    row = {"event_id": "e1", "source_ts_ms": 1, "receive_ts_ms": 2, "venue": "hyperliquid", "symbol": "BTC", "kind": "trade"}
    assert native_event_contract_receipt(row)["status"] == "PROVEN"


def test_hvr_0002_required_field_missing():
    assert required_field_receipt({}, field="event_id")["status"] == "REJECTED"


def test_hvr_0003_required_field_null():
    assert required_field_receipt({"event_id": None}, field="event_id")["status"] == "REJECTED"


def test_hvr_0004_required_field_type_contract():
    assert required_field_receipt({"event_id": "e1"}, field="event_id")["status"] == "PROVEN"


def test_hvr_0005_non_finite_rejected():
    assert finite_field_receipt(float("nan"))["status"] == "REJECTED"


def test_hvr_0006_cutoff_boundary():
    assert cutoff_boundary_receipt(event_ts_ms=10, cutoff_ts_ms=10)["status"] == "PROVEN"


def test_hvr_0007_old_event_rejected():
    assert age_boundary_receipt(event_ts_ms=5, oldest_allowed_ts_ms=10)["status"] == "REJECTED"


def test_hvr_0008_duplicates_rejected():
    assert duplicate_event_receipt(event_ids=["e1", "e1"])["status"] == "REJECTED"


def test_hvr_0009_retry_is_bounded():
    assert retry_recovery_receipt(attempts=2, max_attempts=3, recovered=True, checkpoint_saved=True)["status"] == "PROVEN"


def test_hvr_0010_replay_is_deterministic():
    assert replay_determinism_receipt(outputs=[{"x": 1}, {"x": 1}])["status"] == "PROVEN"


def test_hvr_0011_snapshot_then_delta():
    assert snapshot_delta_order_receipt(events=[{"kind": "snapshot"}, {"kind": "delta"}])["status"] == "PROVEN"


def test_hvr_0012_delta_without_snapshot_rejected():
    assert delta_before_snapshot_receipt(events=[{"kind": "delta"}])["status"] == "PROVEN"


def test_hvr_0013_sequence_reset_repaired():
    assert sequence_reset_receipt(previous_sequence=3, current_sequence=1, repair_observed=True)["status"] == "PROVEN"


def test_hvr_0014_checksum_mismatch_rejected():
    assert checksum_receipt(expected="a", actual="b")["status"] == "REJECTED"


def test_hvr_0015_instrument_mapping_change_bound():
    assert instrument_mapping_receipt(before="BTC", after="BTC-PERP", mapping_acknowledged=True)["status"] == "PROVEN"


def test_hvr_0016_pagination_complete():
    assert pagination_complete_receipt(page_indices=[0, 1, 2], expected_last_page=2)["status"] == "PROVEN"


def test_hvr_0017_rate_limit_bounded():
    assert rate_limit_retry_receipt(attempts=2, max_attempts=3, retry_after_ms=100)["status"] == "PROVEN"


def test_hvr_0018_l2_trade_consistent():
    assert l2_trade_consistency_receipt(trade_price=101, best_bid=100, best_ask=102)["status"] == "PROVEN"


def test_hvr_0019_engine_timestamp_present():
    assert engine_timestamp_receipt(source_ts_ms=1, receive_ts_ms=2)["status"] == "PROVEN"


def test_hvr_0020_reconnect_repaired():
    assert reconnect_repair_receipt(reconnected=True, resync_snapshot=True, sequence_recovered=True)["status"] == "PROVEN"


def test_native_payload_hash_is_verified():
    payload = b"safe-native-payload"
    assert native_payload_hash_receipt(payload=payload, expected_sha256=hashlib.sha256(payload).hexdigest())["status"] == "PROVEN"
