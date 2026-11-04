from hl_observer.copy_vault.per_coin_serialization import (
    VerrouParCoin,
    serialization_add_without_position_receipt,
    serialization_age_receipt,
    serialization_close_remaining_receipt,
    serialization_close_without_position_receipt,
    serialization_concurrent_add_close_receipt,
    serialization_contract_receipt,
    serialization_cutoff_receipt,
    serialization_duplicate_receipt,
    serialization_field_type_receipt,
    serialization_finite_receipt,
    serialization_flip_receipt,
    serialization_leverage_receipt,
    serialization_open_long_receipt,
    serialization_open_short_receipt,
    serialization_reduce_only_receipt,
    serialization_reduce_without_position_receipt,
    serialization_replay_receipt,
    serialization_required_field_receipt,
    serialization_retry_receipt,
    serialization_receipt,
)


def test_hvr_0281_serialization_baseline():
    assert serialization_receipt(vault="v", coin="BTC")["status"] == "PROVEN"
    lock = VerrouParCoin(); assert lock.acquerir("v", "BTC")["ok"] is True
    assert lock.acquerir("v", "BTC")["ok"] is False


def test_hvr_0282_contract():
    row = {"vault": "v", "coin": "BTC", "fill_id": "f", "event_ts_ms": 10, "receive_ts_ms": 11}
    assert serialization_contract_receipt(row)["status"] == "PROVEN"


def test_hvr_0283_required_field():
    assert serialization_required_field_receipt({}, field="vault")["status"] == "REJECTED"


def test_hvr_0284_required_null():
    assert serialization_required_field_receipt({"vault": None}, field="vault")["status"] == "REJECTED"


def test_hvr_0285_field_type():
    assert serialization_field_type_receipt({"sequence": 1}, field="sequence", expected_type=int)["status"] == "PROVEN"


def test_hvr_0286_nonfinite():
    assert serialization_finite_receipt(float("nan"))["status"] == "REJECTED"


def test_hvr_0287_cutoff():
    assert serialization_cutoff_receipt(event_ts_ms=10, cutoff_ts_ms=10)["status"] == "PROVEN"


def test_hvr_0288_old_event():
    assert serialization_age_receipt(event_ts_ms=9, oldest_allowed_ts_ms=10)["status"] == "REJECTED"


def test_hvr_0289_duplicate():
    assert serialization_duplicate_receipt(event_ids=["e", "e"])["status"] == "REJECTED"


def test_hvr_0290_retry():
    assert serialization_retry_receipt(attempts=2, max_attempts=3, checkpoint_saved=True)["status"] == "PROVEN"


def test_hvr_0291_replay():
    assert serialization_replay_receipt(outputs=[{"lock": True}, {"lock": True}])["status"] == "PROVEN"


def test_hvr_0292_open_long():
    assert serialization_open_long_receipt(current_position=0, target_position=1)["status"] == "PROVEN"


def test_hvr_0293_open_short():
    assert serialization_open_short_receipt(current_position=0, target_position=-1)["status"] == "PROVEN"


def test_hvr_0294_add_without_position():
    assert serialization_add_without_position_receipt(action="ADD", current_position=0)["status"] == "REJECTED"


def test_hvr_0295_reduce_without_position():
    assert serialization_reduce_without_position_receipt(action="REDUCE", current_position=0)["status"] == "REJECTED"


def test_hvr_0296_close_without_position():
    assert serialization_close_without_position_receipt(action="CLOSE", current_position=0)["status"] == "REJECTED"


def test_hvr_0297_flip():
    assert serialization_flip_receipt(from_position=1, to_position=-1, intermediate_close=True)["status"] == "PROVEN"


def test_hvr_0298_reduce_only():
    assert serialization_reduce_only_receipt(current_position=2, target_position=1, reduce_only=True)["status"] == "PROVEN"


def test_hvr_0299_close_remaining():
    assert serialization_close_remaining_receipt(current_position=2, close_size=2)["status"] == "PROVEN"


def test_hvr_0300_leverage_and_concurrent():
    assert serialization_leverage_receipt(leverage=2.0)["status"] == "PROVEN"
    assert serialization_concurrent_add_close_receipt(actions=["ADD", "CLOSE"], ordered=True)["status"] == "PROVEN"
