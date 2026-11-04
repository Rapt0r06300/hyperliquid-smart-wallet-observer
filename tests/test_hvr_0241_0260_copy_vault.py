from hl_observer.copy_vault.partial_close_ratio import (
    ratio_add_without_position_receipt,
    ratio_age_receipt,
    ratio_close_remaining_receipt,
    ratio_close_without_position_receipt,
    ratio_concurrent_add_close_receipt,
    ratio_contract_receipt,
    ratio_cutoff_receipt,
    ratio_duplicate_receipt,
    ratio_field_type_receipt,
    ratio_finite_receipt,
    ratio_flip_receipt,
    ratio_fermeture,
    ratio_leverage_receipt,
    ratio_open_long_receipt,
    ratio_open_short_receipt,
    ratio_reduce_only_receipt,
    ratio_reduce_without_position_receipt,
    ratio_replay_receipt,
    ratio_required_field_receipt,
    ratio_retry_receipt,
    ratio_done_receipt,
)


def test_hvr_0241_ratio_baseline():
    assert ratio_fermeture(3.0, 10.0, notre_position=5.0)["pct"] == 0.3


def test_hvr_0242_contract():
    row = {"wallet": "w", "reduced_quantity": 3.0, "leader_position_before": 10.0, "event_ts_ms": 10, "receive_ts_ms": 11}
    assert ratio_contract_receipt(row)["status"] == "PROVEN"


def test_hvr_0243_required_field():
    assert ratio_required_field_receipt({}, field="wallet")["status"] == "REJECTED"


def test_hvr_0244_required_null():
    assert ratio_required_field_receipt({"wallet": None}, field="wallet")["status"] == "REJECTED"


def test_hvr_0245_field_type():
    assert ratio_field_type_receipt({"quantity": 1.0}, field="quantity", expected_type=float)["status"] == "PROVEN"
    assert ratio_field_type_receipt({"quantity": "1"}, field="quantity", expected_type=float)["status"] == "REJECTED"


def test_hvr_0246_nonfinite():
    assert ratio_finite_receipt(float("nan"))["status"] == "REJECTED"


def test_hvr_0247_cutoff():
    assert ratio_cutoff_receipt(event_ts_ms=10, cutoff_ts_ms=10)["status"] == "PROVEN"


def test_hvr_0248_old_event():
    assert ratio_age_receipt(event_ts_ms=9, oldest_allowed_ts_ms=10)["status"] == "REJECTED"


def test_hvr_0249_duplicate():
    assert ratio_duplicate_receipt(event_ids=["e", "e"])["status"] == "REJECTED"


def test_hvr_0250_retry():
    assert ratio_retry_receipt(attempts=2, max_attempts=3, checkpoint_saved=True)["status"] == "PROVEN"


def test_hvr_0251_replay():
    assert ratio_replay_receipt(outputs=[{"pct": 0.3}, {"pct": 0.3}])["status"] == "PROVEN"


def test_hvr_0252_open_long():
    assert ratio_open_long_receipt(current_position=0, target_position=1)["status"] == "PROVEN"


def test_hvr_0253_open_short():
    assert ratio_open_short_receipt(current_position=0, target_position=-1)["status"] == "PROVEN"


def test_hvr_0254_add_without_position():
    assert ratio_add_without_position_receipt(action="ADD", current_position=0)["status"] == "REJECTED"


def test_hvr_0255_reduce_without_position():
    assert ratio_reduce_without_position_receipt(action="REDUCE", current_position=0)["status"] == "REJECTED"


def test_hvr_0256_close_without_position():
    assert ratio_close_without_position_receipt(action="CLOSE", current_position=0)["status"] == "REJECTED"


def test_hvr_0257_flip():
    assert ratio_flip_receipt(from_position=1, to_position=-1, intermediate_close=True)["status"] == "PROVEN"


def test_hvr_0258_reduce_only():
    assert ratio_reduce_only_receipt(current_position=2, target_position=1, reduce_only=True)["status"] == "PROVEN"
    assert ratio_reduce_only_receipt(current_position=2, target_position=3, reduce_only=True)["status"] == "REJECTED"


def test_hvr_0259_close_remaining():
    assert ratio_close_remaining_receipt(current_position=2, close_size=2)["status"] == "PROVEN"
    assert ratio_close_remaining_receipt(current_position=2, close_size=3)["status"] == "REJECTED"


def test_hvr_0260_leverage_and_concurrent():
    assert ratio_leverage_receipt(leverage=2.0)["status"] == "PROVEN"
    assert ratio_concurrent_add_close_receipt(actions=["ADD", "CLOSE"], ordered=True)["status"] == "PROVEN"


def test_hvr_0260_done_gate_requires_all_checks():
    checks = [
        ratio_contract_receipt({"wallet": "w", "reduced_quantity": 3.0, "leader_position_before": 10.0, "event_ts_ms": 10, "receive_ts_ms": 11}),
        ratio_cutoff_receipt(event_ts_ms=10, cutoff_ts_ms=10),
        ratio_concurrent_add_close_receipt(actions=["ADD", "CLOSE"], ordered=True),
    ]
    assert ratio_done_receipt(checks=checks)["status"] == "PROVEN"
    assert ratio_done_receipt(checks=checks + [{"status": "REJECTED"}])["status"] == "REJECTED"
