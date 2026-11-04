from hl_observer.copy_vault.target_exposure_reconciliation import (
    exposure_add_without_position_receipt,
    exposure_age_receipt,
    exposure_close_remaining_receipt,
    exposure_close_without_position_receipt,
    exposure_concurrent_add_close_receipt,
    exposure_contract_receipt,
    exposure_cutoff_receipt,
    exposure_duplicate_receipt,
    exposure_field_type_receipt,
    exposure_finite_receipt,
    exposure_flip_receipt,
    exposure_leverage_receipt,
    exposure_open_long_receipt,
    exposure_open_short_receipt,
    exposure_reduce_only_receipt,
    exposure_reduce_without_position_receipt,
    exposure_replay_receipt,
    exposure_required_field_receipt,
    exposure_retry_receipt,
    reconcilier,
)


def test_hvr_0201_reconciliation_baseline():
    assert reconcilier(10.0, 10.0)["aligne"] is True
    assert reconcilier(10.0, 9.0)["ajustement"] == 1.0


def test_hvr_0202_contract():
    row = {"wallet": "w", "target_exposure": 2.0, "paper_exposure": 1.0, "event_ts_ms": 10, "receive_ts_ms": 11}
    assert exposure_contract_receipt(row)["status"] == "PROVEN"


def test_hvr_0203_required_field():
    assert exposure_required_field_receipt({}, field="wallet")["status"] == "REJECTED"
    assert exposure_required_field_receipt({"wallet": "w"}, field="wallet")["status"] == "PROVEN"


def test_hvr_0204_field_type():
    assert exposure_field_type_receipt({"position": 1.0}, field="position", expected_type=float)["status"] == "PROVEN"
    assert exposure_field_type_receipt({"position": "1"}, field="position", expected_type=float)["status"] == "REJECTED"


def test_hvr_0205_nonfinite():
    assert exposure_finite_receipt(float("nan"))["status"] == "REJECTED"


def test_hvr_0206_cutoff():
    assert exposure_cutoff_receipt(event_ts_ms=10, cutoff_ts_ms=10)["status"] == "PROVEN"


def test_hvr_0207_old_event():
    assert exposure_age_receipt(event_ts_ms=9, oldest_allowed_ts_ms=10)["status"] == "REJECTED"


def test_hvr_0208_duplicate():
    assert exposure_duplicate_receipt(event_ids=["e", "e"])["status"] == "REJECTED"


def test_hvr_0209_retry():
    assert exposure_retry_receipt(attempts=2, max_attempts=3, checkpoint_saved=True)["status"] == "PROVEN"


def test_hvr_0210_replay():
    assert exposure_replay_receipt(outputs=[{"delta": 1}, {"delta": 1}])["status"] == "PROVEN"


def test_hvr_0211_open_long():
    assert exposure_open_long_receipt(current_position=0, target_position=1)["status"] == "PROVEN"


def test_hvr_0212_open_short():
    assert exposure_open_short_receipt(current_position=0, target_position=-1)["status"] == "PROVEN"


def test_hvr_0213_add_without_position():
    assert exposure_add_without_position_receipt(action="ADD", current_position=0)["status"] == "REJECTED"
    assert exposure_add_without_position_receipt(action="ADD", current_position=1)["status"] == "PROVEN"


def test_hvr_0214_reduce_without_position():
    assert exposure_reduce_without_position_receipt(action="REDUCE", current_position=0)["status"] == "REJECTED"


def test_hvr_0215_close_without_position():
    assert exposure_close_without_position_receipt(action="CLOSE", current_position=0)["status"] == "REJECTED"


def test_hvr_0216_flip():
    assert exposure_flip_receipt(from_position=1, to_position=-1, intermediate_close=True)["status"] == "PROVEN"
    assert exposure_flip_receipt(from_position=1, to_position=-1, intermediate_close=False)["status"] == "REJECTED"


def test_hvr_0217_reduce_only():
    assert exposure_reduce_only_receipt(current_position=2, target_position=1, reduce_only=True)["status"] == "PROVEN"
    assert exposure_reduce_only_receipt(current_position=2, target_position=3, reduce_only=True)["status"] == "REJECTED"


def test_hvr_0218_close_remaining():
    assert exposure_close_remaining_receipt(current_position=2, close_size=2)["status"] == "PROVEN"
    assert exposure_close_remaining_receipt(current_position=2, close_size=3)["status"] == "REJECTED"


def test_hvr_0219_leverage():
    assert exposure_leverage_receipt(leverage=2.0)["status"] == "PROVEN"
    assert exposure_leverage_receipt(leverage=None)["status"] == "UNMEASURABLE"


def test_hvr_0220_concurrent_add_close():
    assert exposure_concurrent_add_close_receipt(actions=["ADD", "CLOSE"], ordered=True)["status"] == "PROVEN"
    assert exposure_concurrent_add_close_receipt(actions=["ADD", "CLOSE"], ordered=False)["status"] == "REJECTED"
