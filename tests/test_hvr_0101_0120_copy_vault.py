from hl_observer.copy_vault.exactly_once_source_fill import (
    backfill_overlap_receipt, close_open_receipt, fill_hash_receipt,
    fill_tid_receipt, heartbeat_continuity_receipt, identity_stability_receipt,
    position_fill_consistency_receipt, same_timestamp_fill_receipt,
    side_consistency_receipt, source_fill_age_receipt,
    source_fill_contract_receipt, source_fill_cutoff_receipt,
    source_fill_duplicate_receipt, source_fill_finite_receipt,
    source_fill_replay_receipt, source_fill_required_field_receipt,
    source_fill_retry_receipt, wallet_source_receipt,
)


def test_hvr_0101_source_contract():
    assert source_fill_contract_receipt({"wallet": "w", "tid": "t", "oid": "o", "hash": "abcdefgh", "source_ts_ms": 1, "receive_ts_ms": 2})["status"] == "PROVEN"


def test_hvr_0102_missing_field():
    assert source_fill_required_field_receipt({}, field="wallet")["status"] == "REJECTED"


def test_hvr_0103_null_field():
    assert source_fill_required_field_receipt({"wallet": None}, field="wallet")["status"] == "REJECTED"


def test_hvr_0104_field_present():
    assert source_fill_required_field_receipt({"wallet": "w"}, field="wallet")["status"] == "PROVEN"


def test_hvr_0105_nonfinite():
    assert source_fill_finite_receipt(float("nan"))["status"] == "REJECTED"


def test_hvr_0106_cutoff():
    assert source_fill_cutoff_receipt(event_ts_ms=10, cutoff_ts_ms=10)["status"] == "PROVEN"


def test_hvr_0107_age():
    assert source_fill_age_receipt(event_ts_ms=10, oldest_allowed_ts_ms=20)["status"] == "REJECTED"


def test_hvr_0108_duplicate():
    assert source_fill_duplicate_receipt(identities=["w#tid:1:x", "w#tid:1:x"])["status"] == "REJECTED"


def test_hvr_0109_retry():
    assert source_fill_retry_receipt(attempts=2, max_attempts=3, checkpoint_saved=True)["status"] == "PROVEN"


def test_hvr_0110_replay():
    assert source_fill_replay_receipt(outputs=[1, 1])["status"] == "PROVEN"


def test_hvr_0111_rest_ws_identity():
    row = {"wallet": "w", "tid": "t"}
    assert identity_stability_receipt(row, row)["same_identity"] is True


def test_hvr_0112_same_timestamp_distinct():
    assert same_timestamp_fill_receipt(fills=[{"wallet": "w", "tid": "1"}, {"wallet": "w", "tid": "2"}])["status"] == "PROVEN"


def test_hvr_0113_tid_present():
    assert fill_tid_receipt({"tid": "t"})["status"] == "PROVEN"


def test_hvr_0114_hash_present():
    assert fill_hash_receipt({"hash": "abcdefgh"})["status"] == "PROVEN"


def test_hvr_0115_close_requires_open():
    assert close_open_receipt(open_ids=["p1"], close_ids=["p1"])["status"] == "PROVEN"


def test_hvr_0116_wallet_matches():
    assert wallet_source_receipt(expected_wallet="w", observed_wallet="w")["status"] == "PROVEN"


def test_hvr_0117_side_matches():
    assert side_consistency_receipt(declared_side="buy", source_side="buy")["status"] == "PROVEN"


def test_hvr_0118_backfill_overlap_analyzed():
    assert backfill_overlap_receipt(existing_ids=["e1"], backfill_ids=["e1"], overlap_analyzed=True)["status"] == "PROVEN"


def test_hvr_0119_position_matches_fills():
    assert position_fill_consistency_receipt(position_delta=3.0, fill_deltas=[1.0, 2.0])["status"] == "PROVEN"


def test_hvr_0120_heartbeat_continuous():
    assert heartbeat_continuity_receipt(previous_ts_ms=10, current_ts_ms=20, max_gap_ms=20)["status"] == "PROVEN"
