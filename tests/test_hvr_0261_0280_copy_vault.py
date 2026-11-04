from hl_observer.copy_vault.post_fill_source_confirmation import (
    confirmer,
    post_fill_add_without_position_receipt,
    post_fill_age_receipt,
    post_fill_close_remaining_receipt,
    post_fill_close_without_position_receipt,
    post_fill_concurrent_add_close_receipt,
    post_fill_contract_receipt,
    post_fill_cutoff_receipt,
    post_fill_duplicate_receipt,
    post_fill_field_type_receipt,
    post_fill_finite_receipt,
    post_fill_flip_receipt,
    post_fill_leverage_receipt,
    post_fill_open_long_receipt,
    post_fill_open_short_receipt,
    post_fill_reduce_only_receipt,
    post_fill_reduce_without_position_receipt,
    post_fill_replay_receipt,
    post_fill_required_field_receipt,
    post_fill_retry_receipt,
)


def test_hvr_0261_post_fill_baseline():
    assert confirmer(2.0, 1.5, 3.5)["confirme"] is True
    assert confirmer(2.0, 1.5, 5.0)["confirme"] is False


def test_hvr_0262_contract():
    row = {"wallet": "w", "position_before": 2.0, "delta": 1.5, "snapshot_after": 3.5, "event_ts_ms": 10, "receive_ts_ms": 11}
    assert post_fill_contract_receipt(row)["status"] == "PROVEN"


def test_hvr_0263_required_field():
    assert post_fill_required_field_receipt({}, field="wallet")["status"] == "REJECTED"


def test_hvr_0264_required_null():
    assert post_fill_required_field_receipt({"wallet": None}, field="wallet")["status"] == "REJECTED"


def test_hvr_0265_field_type():
    assert post_fill_field_type_receipt({"delta": 1.0}, field="delta", expected_type=float)["status"] == "PROVEN"
    assert post_fill_field_type_receipt({"delta": "1"}, field="delta", expected_type=float)["status"] == "REJECTED"


def test_hvr_0266_nonfinite():
    assert post_fill_finite_receipt(float("nan"))["status"] == "REJECTED"


def test_hvr_0267_cutoff():
    assert post_fill_cutoff_receipt(event_ts_ms=10, cutoff_ts_ms=10)["status"] == "PROVEN"


def test_hvr_0268_old_event():
    assert post_fill_age_receipt(event_ts_ms=9, oldest_allowed_ts_ms=10)["status"] == "REJECTED"


def test_hvr_0269_duplicate():
    assert post_fill_duplicate_receipt(event_ids=["e", "e"])["status"] == "REJECTED"


def test_hvr_0270_retry():
    assert post_fill_retry_receipt(attempts=2, max_attempts=3, checkpoint_saved=True)["status"] == "PROVEN"


def test_hvr_0271_replay():
    assert post_fill_replay_receipt(outputs=[{"confirmed": True}, {"confirmed": True}])["status"] == "PROVEN"


def test_hvr_0272_open_long():
    assert post_fill_open_long_receipt(current_position=0, target_position=1)["status"] == "PROVEN"


def test_hvr_0273_open_short():
    assert post_fill_open_short_receipt(current_position=0, target_position=-1)["status"] == "PROVEN"


def test_hvr_0274_add_without_position():
    assert post_fill_add_without_position_receipt(action="ADD", current_position=0)["status"] == "REJECTED"


def test_hvr_0275_reduce_without_position():
    assert post_fill_reduce_without_position_receipt(action="REDUCE", current_position=0)["status"] == "REJECTED"


def test_hvr_0276_close_without_position():
    assert post_fill_close_without_position_receipt(action="CLOSE", current_position=0)["status"] == "REJECTED"


def test_hvr_0277_flip():
    assert post_fill_flip_receipt(from_position=1, to_position=-1, intermediate_close=True)["status"] == "PROVEN"


def test_hvr_0278_reduce_only():
    assert post_fill_reduce_only_receipt(current_position=2, target_position=1, reduce_only=True)["status"] == "PROVEN"


def test_hvr_0279_close_remaining():
    assert post_fill_close_remaining_receipt(current_position=2, close_size=2)["status"] == "PROVEN"


def test_hvr_0280_leverage_and_concurrent():
    assert post_fill_leverage_receipt(leverage=2.0)["status"] == "PROVEN"
    assert post_fill_concurrent_add_close_receipt(actions=["ADD", "CLOSE"], ordered=True)["status"] == "PROVEN"
