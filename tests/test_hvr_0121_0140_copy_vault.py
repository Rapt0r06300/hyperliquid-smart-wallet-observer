from hl_observer.copy_vault.ws_rest_disagreement_quarantine import (
    quarantine_age_receipt, quarantine_backfill_receipt,
    quarantine_close_open_receipt, quarantine_cutoff_receipt,
    quarantine_duplicate_receipt, quarantine_event_contract_receipt,
    quarantine_finite_receipt, quarantine_hash_receipt,
    quarantine_heartbeat_receipt, quarantine_position_receipt,
    quarantine_replay_receipt, quarantine_required_field_receipt,
    quarantine_retry_receipt, quarantine_side_receipt,
    quarantine_tid_receipt, quarantine_wallet_receipt, quarantine_done_receipt,
    rest_ws_fill_receipt, same_timestamp_quarantine_receipt,
)


def test_hvr_0121_contract():
    assert quarantine_event_contract_receipt({"vault": "v", "source": "ws", "event_id": "e", "source_ts_ms": 1, "receive_ts_ms": 2})["status"] == "PROVEN"


def test_hvr_0122_missing():
    assert quarantine_required_field_receipt({}, field="vault")["status"] == "REJECTED"


def test_hvr_0123_null():
    assert quarantine_required_field_receipt({"vault": None}, field="vault")["status"] == "REJECTED"


def test_hvr_0124_present():
    assert quarantine_required_field_receipt({"vault": "v"}, field="vault")["status"] == "PROVEN"


def test_hvr_0125_nonfinite():
    assert quarantine_finite_receipt(float("nan"))["status"] == "REJECTED"


def test_hvr_0126_cutoff():
    assert quarantine_cutoff_receipt(event_ts_ms=10, cutoff_ts_ms=10)["status"] == "PROVEN"


def test_hvr_0127_old():
    assert quarantine_age_receipt(event_ts_ms=5, oldest_allowed_ts_ms=10)["status"] == "REJECTED"


def test_hvr_0128_duplicate():
    assert quarantine_duplicate_receipt(event_ids=["e", "e"])["status"] == "REJECTED"


def test_hvr_0129_retry():
    assert quarantine_retry_receipt(attempts=2, max_attempts=3, checkpoint_saved=True)["status"] == "PROVEN"


def test_hvr_0130_replay():
    assert quarantine_replay_receipt(outputs=[1, 1])["status"] == "PROVEN"


def test_hvr_0131_rest_ws():
    assert rest_ws_fill_receipt(ws_identity="w#1", rest_identity="w#1")["status"] == "PROVEN"


def test_hvr_0132_timestamp_distinct():
    assert same_timestamp_quarantine_receipt(identities=["e1", "e2"])["status"] == "PROVEN"


def test_hvr_0133_tid():
    assert quarantine_tid_receipt({"tid": "t"})["status"] == "PROVEN"


def test_hvr_0134_hash():
    assert quarantine_hash_receipt({"hash": "abcdefgh"})["status"] == "PROVEN"


def test_hvr_0135_close_open():
    assert quarantine_close_open_receipt(open_ids=["p1"], close_ids=["p1"])["status"] == "PROVEN"


def test_hvr_0136_wallet():
    assert quarantine_wallet_receipt(expected_wallet="w", observed_wallet="w")["status"] == "PROVEN"


def test_hvr_0137_side():
    assert quarantine_side_receipt(declared_side="buy", source_side="buy")["status"] == "PROVEN"


def test_hvr_0138_backfill():
    assert quarantine_backfill_receipt(existing_ids=["e"], backfill_ids=["e"], overlap_analyzed=True)["status"] == "PROVEN"


def test_hvr_0139_position():
    assert quarantine_position_receipt(position_delta=3.0, fill_deltas=[1.0, 2.0])["status"] == "PROVEN"


def test_hvr_0140_heartbeat():
    assert quarantine_heartbeat_receipt(previous_ts_ms=10, current_ts_ms=20, max_gap_ms=20)["status"] == "PROVEN"


def test_hvr_0140_done_gate_requires_all_checks():
    checks = [
        quarantine_event_contract_receipt({"vault": "v", "source": "ws", "event_id": "e", "source_ts_ms": 1, "receive_ts_ms": 2}),
        quarantine_cutoff_receipt(event_ts_ms=10, cutoff_ts_ms=10),
        quarantine_heartbeat_receipt(previous_ts_ms=10, current_ts_ms=20, max_gap_ms=20),
    ]
    assert quarantine_done_receipt(checks=checks)["status"] == "PROVEN"
    assert quarantine_done_receipt(checks=checks + [{"status": "REJECTED"}])["status"] == "REJECTED"
