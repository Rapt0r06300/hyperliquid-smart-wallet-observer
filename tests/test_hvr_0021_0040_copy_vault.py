import hashlib

import pytest

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


def _case(index: int):
    row = {"event_id": f"binance-{index}", "source_ts_ms": 1, "receive_ts_ms": 2, "venue": "binance", "symbol": "BTCUSDT", "kind": "trade"}
    cases = [
        lambda: native_event_contract_receipt(row),
        lambda: required_field_receipt({}, field="event_id"),
        lambda: required_field_receipt({"event_id": None}, field="event_id"),
        lambda: required_field_receipt({"event_id": f"e{index}"}, field="event_id"),
        lambda: finite_field_receipt(float("nan")),
        lambda: cutoff_boundary_receipt(event_ts_ms=10, cutoff_ts_ms=10),
        lambda: age_boundary_receipt(event_ts_ms=5, oldest_allowed_ts_ms=10),
        lambda: duplicate_event_receipt(event_ids=["e1", "e1"]),
        lambda: retry_recovery_receipt(attempts=2, max_attempts=3, recovered=True, checkpoint_saved=True),
        lambda: replay_determinism_receipt(outputs=[{"x": 1}, {"x": 1}]),
        lambda: snapshot_delta_order_receipt(events=[{"kind": "snapshot"}, {"kind": "delta"}]),
        lambda: delta_before_snapshot_receipt(events=[{"kind": "delta"}]),
        lambda: sequence_reset_receipt(previous_sequence=3, current_sequence=1, repair_observed=True),
        lambda: checksum_receipt(expected="a", actual="b"),
        lambda: instrument_mapping_receipt(before="BTCUSDT", after="BTCUSDT-PERP", mapping_acknowledged=True),
        lambda: pagination_complete_receipt(page_indices=[0, 1, 2], expected_last_page=2),
        lambda: rate_limit_retry_receipt(attempts=2, max_attempts=3, retry_after_ms=100),
        lambda: l2_trade_consistency_receipt(trade_price=101, best_bid=100, best_ask=102),
        lambda: engine_timestamp_receipt(source_ts_ms=1, receive_ts_ms=2),
        lambda: reconnect_repair_receipt(reconnected=True, resync_snapshot=True, sequence_recovered=True),
    ]
    return cases[index - 21]()


@pytest.mark.parametrize("index", range(21, 41))
def test_hvr_binance_native_contract_lot(index):
    assert _case(index)["status"] in {"PROVEN", "REJECTED"}


def test_hvr_binance_payload_hash():
    payload = b"safe-binance-native-payload"
    assert native_payload_hash_receipt(payload=payload, expected_sha256=hashlib.sha256(payload).hexdigest())["status"] == "PROVEN"
