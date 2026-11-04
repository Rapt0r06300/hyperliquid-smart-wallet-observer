from hl_observer.copy_vault.position_epoch_id import (
    creer_epoch_id,
    epoch_add_without_position_receipt,
    epoch_age_receipt,
    epoch_close_remaining_receipt,
    epoch_close_without_position_receipt,
    epoch_concurrent_add_close_receipt,
    epoch_contract_receipt,
    epoch_cutoff_receipt,
    epoch_duplicate_receipt,
    epoch_field_type_receipt,
    epoch_finite_receipt,
    epoch_flip_receipt,
    epoch_leverage_receipt,
    epoch_open_long_receipt,
    epoch_open_short_receipt,
    epoch_reduce_only_receipt,
    epoch_reduce_without_position_receipt,
    epoch_replay_receipt,
    epoch_required_field_receipt,
    epoch_retry_receipt,
    epoch_done_receipt,
)


def test_hvr_0221_epoch_baseline():
    result = creer_epoch_id(wallet="w", instrument="BTC", sequence=1, snapshot_ts_ms=10)
    assert result["status"] == "PROVEN" and len(result["epoch_id"]) == 64


def test_hvr_0222_contract():
    row = {"epoch_id": "e", "wallet": "w", "instrument": "BTC", "sequence": 1, "snapshot_ts_ms": 10, "receive_ts_ms": 11}
    assert epoch_contract_receipt(row)["status"] == "PROVEN"


def test_hvr_0223_required_missing():
    assert epoch_required_field_receipt({}, field="wallet")["status"] == "REJECTED"


def test_hvr_0224_required_null():
    assert epoch_required_field_receipt({"wallet": None}, field="wallet")["status"] == "REJECTED"


def test_hvr_0225_field_type():
    assert epoch_field_type_receipt({"sequence": 1}, field="sequence", expected_type=int)["status"] == "PROVEN"
    assert epoch_field_type_receipt({"sequence": "1"}, field="sequence", expected_type=int)["status"] == "REJECTED"


def test_hvr_0226_nonfinite():
    assert epoch_finite_receipt(float("nan"))["status"] == "REJECTED"


def test_hvr_0227_cutoff():
    assert epoch_cutoff_receipt(event_ts_ms=10, cutoff_ts_ms=10)["status"] == "PROVEN"


def test_hvr_0228_old_event():
    assert epoch_age_receipt(event_ts_ms=9, oldest_allowed_ts_ms=10)["status"] == "REJECTED"


def test_hvr_0229_duplicate():
    assert epoch_duplicate_receipt(event_ids=["e", "e"])["status"] == "REJECTED"


def test_hvr_0230_retry():
    assert epoch_retry_receipt(attempts=2, max_attempts=3, checkpoint_saved=True)["status"] == "PROVEN"


def test_hvr_0231_replay():
    assert epoch_replay_receipt(outputs=[{"epoch": 1}, {"epoch": 1}])["status"] == "PROVEN"


def test_hvr_0232_open_long():
    assert epoch_open_long_receipt(current_position=0, target_position=1)["status"] == "PROVEN"


def test_hvr_0233_open_short():
    assert epoch_open_short_receipt(current_position=0, target_position=-1)["status"] == "PROVEN"


def test_hvr_0234_add_without_position():
    assert epoch_add_without_position_receipt(action="ADD", current_position=0)["status"] == "REJECTED"


def test_hvr_0235_reduce_without_position():
    assert epoch_reduce_without_position_receipt(action="REDUCE", current_position=0)["status"] == "REJECTED"


def test_hvr_0236_close_without_position():
    assert epoch_close_without_position_receipt(action="CLOSE", current_position=0)["status"] == "REJECTED"


def test_hvr_0237_flip():
    assert epoch_flip_receipt(from_position=1, to_position=-1, intermediate_close=True)["status"] == "PROVEN"
    assert epoch_flip_receipt(from_position=1, to_position=-1, intermediate_close=False)["status"] == "REJECTED"


def test_hvr_0238_reduce_only():
    assert epoch_reduce_only_receipt(current_position=2, target_position=1, reduce_only=True)["status"] == "PROVEN"
    assert epoch_reduce_only_receipt(current_position=2, target_position=3, reduce_only=True)["status"] == "REJECTED"


def test_hvr_0239_close_remaining():
    assert epoch_close_remaining_receipt(current_position=2, close_size=2)["status"] == "PROVEN"
    assert epoch_close_remaining_receipt(current_position=2, close_size=3)["status"] == "REJECTED"


def test_hvr_0240_leverage_and_concurrent():
    assert epoch_leverage_receipt(leverage=2.0)["status"] == "PROVEN"
    assert epoch_concurrent_add_close_receipt(actions=["ADD", "CLOSE"], ordered=True)["status"] == "PROVEN"


def test_hvr_0240_done_gate_requires_all_checks():
    checks = [
        epoch_contract_receipt({"epoch_id": "e", "wallet": "w", "instrument": "BTC", "sequence": 1, "snapshot_ts_ms": 10, "receive_ts_ms": 11}),
        epoch_cutoff_receipt(event_ts_ms=10, cutoff_ts_ms=10),
        epoch_concurrent_add_close_receipt(actions=["ADD", "CLOSE"], ordered=True),
    ]
    assert epoch_done_receipt(checks=checks)["status"] == "PROVEN"
    assert epoch_done_receipt(checks=checks + [{"status": "REJECTED"}])["status"] == "REJECTED"
