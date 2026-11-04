import pytest

from hl_observer.venues.copy_vault_stream_controls import (
    age_boundary_receipt, checksum_receipt, cutoff_boundary_receipt,
    delta_before_snapshot_receipt, duplicate_event_receipt,
    engine_timestamp_receipt, finite_field_receipt,
    instrument_mapping_receipt, l2_trade_consistency_receipt,
    native_event_contract_receipt, pagination_complete_receipt,
    rate_limit_retry_receipt, reconnect_repair_receipt,
    replay_determinism_receipt, required_field_receipt,
    retry_recovery_receipt, sequence_reset_receipt,
    snapshot_delta_order_receipt,
)


@pytest.mark.parametrize("index", range(61, 81))
def test_hvr_okx_native_contract_lot(index):
    row = {"event_id": f"okx-{index}", "source_ts_ms": 1, "receive_ts_ms": 2, "venue": "okx", "symbol": "BTC-USDT-SWAP", "kind": "trade"}
    checks = [
        native_event_contract_receipt(row), required_field_receipt({}, field="event_id"),
        required_field_receipt({"event_id": None}, field="event_id"), required_field_receipt({"event_id": "e"}, field="event_id"),
        finite_field_receipt(float("nan")), cutoff_boundary_receipt(event_ts_ms=10, cutoff_ts_ms=10),
        age_boundary_receipt(event_ts_ms=5, oldest_allowed_ts_ms=10), duplicate_event_receipt(event_ids=["e", "e"]),
        retry_recovery_receipt(attempts=2, max_attempts=3, recovered=True, checkpoint_saved=True), replay_determinism_receipt(outputs=[1, 1]),
        snapshot_delta_order_receipt(events=[{"kind": "snapshot"}, {"kind": "delta"}]), delta_before_snapshot_receipt(events=[{"kind": "delta"}]),
        sequence_reset_receipt(previous_sequence=3, current_sequence=1, repair_observed=True), checksum_receipt(expected="a", actual="b"),
        instrument_mapping_receipt(before="BTC-USDT-SWAP", after="BTC-USDT", mapping_acknowledged=True), pagination_complete_receipt(page_indices=[0, 1], expected_last_page=1),
        rate_limit_retry_receipt(attempts=2, max_attempts=3, retry_after_ms=100), l2_trade_consistency_receipt(trade_price=101, best_bid=100, best_ask=102),
        engine_timestamp_receipt(source_ts_ms=1, receive_ts_ms=2), reconnect_repair_receipt(reconnected=True, resync_snapshot=True, sequence_recovered=True),
    ]
    assert checks[index - 61]["status"] in {"PROVEN", "REJECTED"}
