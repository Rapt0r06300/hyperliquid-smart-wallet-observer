from hl_observer.copy_vault.reconnect_overlap_backfill import (
    reconnect_age_receipt, reconnect_close_open_receipt,
    reconnect_contract_receipt, reconnect_cutoff_receipt,
    reconnect_duplicate_receipt, reconnect_finite_receipt,
    reconnect_hash_receipt, reconnect_heartbeat_receipt,
    reconnect_overlap_receipt, reconnect_position_receipt,
    reconnect_replay_receipt, reconnect_required_field_receipt,
    reconnect_rest_ws_receipt, reconnect_retry_receipt,
    reconnect_side_receipt, reconnect_tid_receipt,
    reconnect_timestamp_identity_receipt, reconnect_wallet_receipt,
)


def test_hvr_0141_contract():
    assert reconnect_contract_receipt({"connection_id": "c", "checkpoint_id": "p", "event_id": "e", "receive_ts_ms": 1})["status"] == "PROVEN"


def test_hvr_0142_missing():
    assert reconnect_required_field_receipt({}, field="connection_id")["status"] == "REJECTED"


def test_hvr_0143_null():
    assert reconnect_required_field_receipt({"connection_id": None}, field="connection_id")["status"] == "REJECTED"


def test_hvr_0144_present():
    assert reconnect_required_field_receipt({"connection_id": "c"}, field="connection_id")["status"] == "PROVEN"


def test_hvr_0145_nonfinite():
    assert reconnect_finite_receipt(float("nan"))["status"] == "REJECTED"


def test_hvr_0146_cutoff():
    assert reconnect_cutoff_receipt(event_ts_ms=10, cutoff_ts_ms=10)["status"] == "PROVEN"


def test_hvr_0147_old():
    assert reconnect_age_receipt(event_ts_ms=5, oldest_allowed_ts_ms=10)["status"] == "REJECTED"


def test_hvr_0148_duplicate():
    assert reconnect_duplicate_receipt(event_ids=["e", "e"])["status"] == "REJECTED"


def test_hvr_0149_retry():
    assert reconnect_retry_receipt(attempts=2, max_attempts=3, checkpoint_saved=True)["status"] == "PROVEN"


def test_hvr_0150_replay():
    assert reconnect_replay_receipt(outputs=[1, 1])["status"] == "PROVEN"


def test_hvr_0151_rest_ws():
    assert reconnect_rest_ws_receipt(ws_identity="w#1", rest_identity="w#1")["status"] == "PROVEN"


def test_hvr_0152_timestamp():
    assert reconnect_timestamp_identity_receipt(identities=["e1", "e2"])["status"] == "PROVEN"


def test_hvr_0153_tid():
    assert reconnect_tid_receipt({"tid": "t"})["status"] == "PROVEN"


def test_hvr_0154_hash():
    assert reconnect_hash_receipt({"hash": "abcdefgh"})["status"] == "PROVEN"


def test_hvr_0155_close_open():
    assert reconnect_close_open_receipt(open_ids=["p1"], close_ids=["p1"])["status"] == "PROVEN"


def test_hvr_0156_wallet():
    assert reconnect_wallet_receipt(expected_wallet="w", observed_wallet="w")["status"] == "PROVEN"


def test_hvr_0157_side():
    assert reconnect_side_receipt(declared_side="buy", source_side="buy")["status"] == "PROVEN"


def test_hvr_0158_overlap():
    assert reconnect_overlap_receipt(checkpoint_ms=100, backfill_start_ms=90, overlap_ms=10)["status"] == "PROVEN"


def test_hvr_0159_position():
    assert reconnect_position_receipt(position_delta=3.0, fill_deltas=[1.0, 2.0])["status"] == "PROVEN"


def test_hvr_0160_heartbeat():
    assert reconnect_heartbeat_receipt(previous_ts_ms=10, current_ts_ms=20, max_gap_ms=20)["status"] == "PROVEN"
