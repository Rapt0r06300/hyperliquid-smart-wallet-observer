from hl_observer.copy_vault.leader_state_versioning import (
    VersionneurEtat,
    leader_age_receipt,
    leader_causality_receipt,
    leader_close_open_receipt,
    leader_contract_receipt,
    leader_cutoff_receipt,
    leader_duplicate_receipt,
    leader_finite_receipt,
    leader_field_type_receipt,
    leader_hash_receipt,
    leader_heartbeat_receipt,
    leader_overlap_receipt,
    leader_position_receipt,
    leader_replay_receipt,
    leader_required_field_receipt,
    leader_rest_ws_receipt,
    leader_retry_receipt,
    leader_side_receipt,
    leader_tid_receipt,
    leader_timestamp_identity_receipt,
    leader_wallet_receipt,
)


def test_hvr_0181_versioned_baseline():
    versioned = VersionneurEtat()
    first = versioned.nouveau_snapshot(equity=100.0, positions={"BTC": 1.0})
    second = versioned.nouveau_snapshot(equity=101.0, positions={"BTC": 1.1})
    assert first["version"] == 1 and second["version"] == 2
    assert versioned.obtenir(1)["positions"] == {"BTC": 1.0}


def test_hvr_0182_required_missing():
    assert leader_required_field_receipt({}, field="wallet")["status"] == "REJECTED"


def test_hvr_0183_required_null():
    assert leader_required_field_receipt({"wallet": None}, field="wallet")["status"] == "REJECTED"


def test_hvr_0184_field_type():
    assert leader_field_type_receipt({"version": 1}, field="version", expected_type=int)["status"] == "PROVEN"
    assert leader_field_type_receipt({"version": "1"}, field="version", expected_type=int)["status"] == "REJECTED"


def test_hvr_0185_nonfinite():
    assert leader_finite_receipt(float("nan"))["status"] == "REJECTED"


def test_hvr_0186_cutoff_boundary():
    assert leader_cutoff_receipt(event_ts_ms=10, cutoff_ts_ms=10)["status"] == "PROVEN"


def test_hvr_0187_old_event():
    assert leader_age_receipt(event_ts_ms=9, oldest_allowed_ts_ms=10)["status"] == "REJECTED"


def test_hvr_0188_duplicate():
    assert leader_duplicate_receipt(event_ids=["e", "e"])["status"] == "REJECTED"


def test_hvr_0189_retry():
    assert leader_retry_receipt(attempts=2, max_attempts=3, checkpoint_saved=True)["status"] == "PROVEN"


def test_hvr_0190_replay():
    assert leader_replay_receipt(outputs=[{"version": 1}, {"version": 1}])["status"] == "PROVEN"


def test_hvr_0191_rest_ws():
    assert leader_rest_ws_receipt(ws_identity="s1", rest_identity="s1")["status"] == "PROVEN"


def test_hvr_0192_timestamp_identity():
    assert leader_timestamp_identity_receipt(identities=["t1", "t2"])["status"] == "PROVEN"


def test_hvr_0193_tid_missing():
    assert leader_tid_receipt({})["status"] == "REJECTED"


def test_hvr_0194_hash_missing():
    assert leader_hash_receipt({})["status"] == "REJECTED"
    assert leader_hash_receipt({"hash": "deadbeef"})["status"] == "PROVEN"


def test_hvr_0195_close_open():
    assert leader_close_open_receipt(open_ids=["p"], close_ids=["p"])["status"] == "PROVEN"


def test_hvr_0196_wallet():
    assert leader_wallet_receipt(expected_wallet="w", observed_wallet="w")["status"] == "PROVEN"


def test_hvr_0197_side():
    assert leader_side_receipt(declared_side="buy", source_side="buy")["status"] == "PROVEN"


def test_hvr_0198_overlap():
    assert leader_overlap_receipt(existing_ids=["e"], backfill_ids=["e"], overlap_analyzed=True)["status"] == "PROVEN"


def test_hvr_0199_position():
    assert leader_position_receipt(position_delta=3.0, fill_deltas=[1.0, 2.0])["status"] == "PROVEN"


def test_hvr_0200_heartbeat_and_causality():
    assert leader_heartbeat_receipt(previous_ts_ms=10, current_ts_ms=20, max_gap_ms=20)["status"] == "PROVEN"
    assert leader_causality_receipt(event_ts_ms=10, state_ts_ms=20, observed_before_state=True)["status"] == "PROVEN"


def test_leader_contract_positive():
    row = {
        "wallet": "w", "version": 1, "equity": 100.0, "positions": {"BTC": 1.0},
        "event_ts_ms": 10, "receive_ts_ms": 11,
    }
    assert leader_contract_receipt(row)["status"] == "PROVEN"
