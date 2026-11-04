from hl_observer.copy_vault.position_gap_detector import (
    detecter,
    gap_age_receipt,
    gap_causality_receipt,
    gap_close_open_receipt,
    gap_contract_receipt,
    gap_cutoff_receipt,
    gap_delta_receipt,
    gap_duplicate_receipt,
    gap_finite_receipt,
    gap_hash_receipt,
    gap_heartbeat_receipt,
    gap_overlap_receipt,
    gap_position_receipt,
    gap_replay_receipt,
    gap_required_field_receipt,
    gap_rest_ws_receipt,
    gap_retry_receipt,
    gap_side_receipt,
    gap_tid_receipt,
    gap_timestamp_identity_receipt,
    gap_wallet_receipt,
    gap_done_receipt,
)


def test_hvr_0161_detector_and_delta():
    assert detecter(10.0, [1.0, -0.5], 10.5)["gap"] is False
    assert gap_delta_receipt(before=10.0, fills=[1.0, -0.5], after=10.5)["status"] == "PROVEN"


def test_hvr_0162_contract():
    row = {
        "wallet": "0xabc", "position_before": 1.0, "position_after": 2.0,
        "fills_signed": [1.0], "event_ts_ms": 10, "receive_ts_ms": 11,
    }
    assert gap_contract_receipt(row)["status"] == "PROVEN"


def test_hvr_0163_required_field():
    assert gap_required_field_receipt({}, field="wallet")["status"] == "REJECTED"
    assert gap_required_field_receipt({"wallet": "w"}, field="wallet")["status"] == "PROVEN"


def test_hvr_0164_finite():
    assert gap_finite_receipt(float("nan"))["status"] == "REJECTED"


def test_hvr_0165_cutoff():
    assert gap_cutoff_receipt(event_ts_ms=10, cutoff_ts_ms=10)["status"] == "PROVEN"
    assert gap_cutoff_receipt(event_ts_ms=11, cutoff_ts_ms=10)["status"] == "REJECTED"


def test_hvr_0166_age():
    assert gap_age_receipt(event_ts_ms=10, oldest_allowed_ts_ms=10)["status"] == "PROVEN"
    assert gap_age_receipt(event_ts_ms=9, oldest_allowed_ts_ms=10)["status"] == "REJECTED"


def test_hvr_0167_duplicate():
    assert gap_duplicate_receipt(event_ids=["e1", "e1"])["status"] == "REJECTED"
    assert gap_duplicate_receipt(event_ids=["e1", "e2"])["status"] == "PROVEN"


def test_hvr_0168_retry():
    assert gap_retry_receipt(attempts=2, max_attempts=3, checkpoint_saved=True)["status"] == "PROVEN"
    assert gap_retry_receipt(attempts=4, max_attempts=3, checkpoint_saved=True)["status"] == "REJECTED"


def test_hvr_0169_replay():
    assert gap_replay_receipt(outputs=[{"gap": False}, {"gap": False}])["status"] == "PROVEN"
    assert gap_replay_receipt(outputs=[1, 2])["status"] == "REJECTED"


def test_hvr_0170_rest_ws():
    assert gap_rest_ws_receipt(ws_identity="fill-1", rest_identity="fill-1")["status"] == "PROVEN"


def test_hvr_0171_timestamp_identity():
    assert gap_timestamp_identity_receipt(identities=["t1", "t2"])["status"] == "PROVEN"
    assert gap_timestamp_identity_receipt(identities=["t1", "t1"])["status"] == "REJECTED"


def test_hvr_0172_tid():
    assert gap_tid_receipt({"tid": "tid-1"})["status"] == "PROVEN"
    assert gap_tid_receipt({})["status"] == "REJECTED"


def test_hvr_0173_hash():
    assert gap_hash_receipt({"hash": "deadbeef"})["status"] == "PROVEN"
    assert gap_hash_receipt({"hash": "not-hex"})["status"] == "REJECTED"


def test_hvr_0174_close_open():
    assert gap_close_open_receipt(open_ids=["p1"], close_ids=["p1"])["status"] == "PROVEN"
    assert gap_close_open_receipt(open_ids=[], close_ids=["p1"])["status"] == "REJECTED"


def test_hvr_0175_wallet():
    assert gap_wallet_receipt(expected_wallet="w", observed_wallet="w")["status"] == "PROVEN"
    assert gap_wallet_receipt(expected_wallet="w", observed_wallet="x")["status"] == "REJECTED"


def test_hvr_0176_side():
    assert gap_side_receipt(declared_side="buy", source_side="buy")["status"] == "PROVEN"
    assert gap_side_receipt(declared_side="buy", source_side="sell")["status"] == "REJECTED"


def test_hvr_0177_overlap():
    assert gap_overlap_receipt(existing_ids=["e1"], backfill_ids=["e1"], overlap_analyzed=True)["status"] == "PROVEN"
    assert gap_overlap_receipt(existing_ids=["e1"], backfill_ids=["e1"], overlap_analyzed=False)["status"] == "REJECTED"


def test_hvr_0178_position():
    assert gap_position_receipt(position_delta=3.0, fill_deltas=[1.0, 2.0])["status"] == "PROVEN"
    assert gap_position_receipt(position_delta=4.0, fill_deltas=[1.0, 2.0])["status"] == "REJECTED"


def test_hvr_0179_heartbeat():
    assert gap_heartbeat_receipt(previous_ts_ms=10, current_ts_ms=20, max_gap_ms=20)["status"] == "PROVEN"
    assert gap_heartbeat_receipt(previous_ts_ms=10, current_ts_ms=40, max_gap_ms=20)["status"] == "REJECTED"


def test_hvr_0180_causality():
    assert gap_causality_receipt(event_ts_ms=10, position_ts_ms=20, observed_before_position=True)["status"] == "PROVEN"
    assert gap_causality_receipt(event_ts_ms=21, position_ts_ms=20, observed_before_position=True)["status"] == "REJECTED"


def test_hvr_0180_done_gate_requires_all_checks():
    checks = [
        gap_contract_receipt({"wallet": "0xabc", "position_before": 1.0, "position_after": 2.0, "fills_signed": [1.0], "event_ts_ms": 10, "receive_ts_ms": 11}),
        gap_delta_receipt(before=1.0, fills=[1.0], after=2.0),
        gap_causality_receipt(event_ts_ms=10, position_ts_ms=20, observed_before_position=True),
    ]
    assert gap_done_receipt(checks=checks)["status"] == "PROVEN"
    assert gap_done_receipt(checks=checks + [{"status": "REJECTED"}])["status"] == "REJECTED"
