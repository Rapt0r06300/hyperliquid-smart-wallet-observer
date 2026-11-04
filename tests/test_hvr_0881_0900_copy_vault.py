from hl_observer.simulation.cost_components import (
    SCHEMA_VERSION,
    cost_age_receipt,
    cost_components_safety_receipt,
    cost_cutoff_receipt,
    cost_duplicate_receipt,
    cost_effect_size_receipt,
    cost_embargo_receipt,
    cost_field_type_receipt,
    cost_finite_receipt,
    cost_forward_cutoff_receipt,
    cost_hash_receipt,
    cost_holdout_receipt,
    cost_null_field_receipt,
    cost_partition_receipt,
    cost_pessimistic_edge_receipt,
    cost_replay_receipt,
    cost_required_field_receipt,
    cost_retry_receipt,
    cost_trials_receipt,
    cost_wallet_independence_receipt,
    decompose_execution,
)


def _cost():
    return decompose_execution(
        side="BUY",
        mid_decision=100.0,
        best_touch=100.1,
        avg_fill_price=100.2,
        mid_at_fill=100.3,
        fee_bps=1.0,
    ).to_dict()


def test_hvr_0881_cost_baseline_is_safe():
    result = _cost()
    assert result["schema_version"] == SCHEMA_VERSION
    assert cost_components_safety_receipt(result)["status"] == "PROVEN"
    assert cost_components_safety_receipt({})["status"] == "REJECTED"


def test_hvr_0882_required_field():
    assert cost_required_field_receipt({"coin": "BTC"}, field="coin")["status"] == "PROVEN"
    assert cost_required_field_receipt({}, field="coin")["status"] == "REJECTED"


def test_hvr_0883_null_field():
    assert cost_null_field_receipt({"coin": "BTC"}, field="coin")["status"] == "PROVEN"
    assert cost_null_field_receipt({"coin": None}, field="coin")["status"] == "REJECTED"


def test_hvr_0884_field_type():
    assert cost_field_type_receipt({"amount": 1.0}, field="amount", expected_type=float)["status"] == "PROVEN"
    assert cost_field_type_receipt({"amount": "1"}, field="amount", expected_type=float)["status"] == "REJECTED"


def test_hvr_0885_finite_value():
    assert cost_finite_receipt(1.0)["status"] == "PROVEN"
    assert cost_finite_receipt(float("inf"))["status"] == "REJECTED"


def test_hvr_0886_cutoff_boundary():
    assert cost_cutoff_receipt(event_ts_ms=100, cutoff_ts_ms=100)["status"] == "PROVEN"
    assert cost_cutoff_receipt(event_ts_ms=101, cutoff_ts_ms=100)["status"] == "REJECTED"


def test_hvr_0887_old_event():
    assert cost_age_receipt(event_ts_ms=100, oldest_allowed_ts_ms=100)["status"] == "PROVEN"
    assert cost_age_receipt(event_ts_ms=99, oldest_allowed_ts_ms=100)["status"] == "REJECTED"


def test_hvr_0888_duplicate_event():
    assert cost_duplicate_receipt(event_ids=["a", "b"])["status"] == "PROVEN"
    assert cost_duplicate_receipt(event_ids=["a", "a"])["status"] == "REJECTED"


def test_hvr_0889_retry_is_bounded():
    assert cost_retry_receipt(attempts=2, max_attempts=3, checkpoint_saved=True)["status"] == "PROVEN"
    assert cost_retry_receipt(attempts=4, max_attempts=3, checkpoint_saved=True)["status"] == "REJECTED"


def test_hvr_0890_replay_is_deterministic():
    assert cost_replay_receipt(outputs=[{"cost": 1}, {"cost": 1}])["status"] == "PROVEN"
    assert cost_replay_receipt(outputs=[{"cost": 1}, {"cost": 2}])["status"] == "REJECTED"


def test_hvr_0891_partitions_are_disjoint():
    assert cost_partition_receipt(train_ids=["t"], oos_ids=["o"], forward_ids=["f"])["status"] == "PROVEN"
    assert cost_partition_receipt(train_ids=["t"], oos_ids=["t"], forward_ids=["f"])["status"] == "REJECTED"


def test_hvr_0892_holdout_is_locked():
    assert cost_holdout_receipt(tuned_on_holdout=False, holdout_locked=True)["status"] == "PROVEN"
    assert cost_holdout_receipt(tuned_on_holdout=True, holdout_locked=False)["status"] == "REJECTED"


def test_hvr_0893_embargo_is_sufficient():
    assert cost_embargo_receipt(gap_ms=100, required_gap_ms=50)["status"] == "PROVEN"
    assert cost_embargo_receipt(gap_ms=10, required_gap_ms=50)["status"] == "REJECTED"


def test_hvr_0894_trials_are_recorded():
    assert cost_trials_receipt(trials=3, recorded_trials=3)["status"] == "PROVEN"
    assert cost_trials_receipt(trials=3, recorded_trials=2)["status"] == "REJECTED"


def test_hvr_0895_effect_is_not_single_trade():
    assert cost_effect_size_receipt(trade_count=10, gain=1.0)["status"] == "PROVEN"
    assert cost_effect_size_receipt(trade_count=1, gain=1.0)["status"] == "REJECTED"


def test_hvr_0896_wallets_are_independent():
    assert cost_wallet_independence_receipt(wallet_ids=["w1", "w2"], max_correlation=0.5)["status"] == "PROVEN"
    assert cost_wallet_independence_receipt(wallet_ids=["w1", "w1"], max_correlation=0.5)["status"] == "REJECTED"


def test_hvr_0897_code_hash_does_not_change():
    assert cost_hash_receipt(code_sha_before="c", code_sha_after="c", data_sha_before="d", data_sha_after="d")["status"] == "PROVEN"
    assert cost_hash_receipt(code_sha_before="c", code_sha_after="x", data_sha_before="d", data_sha_after="d")["status"] == "REJECTED"


def test_hvr_0898_data_hash_does_not_change():
    assert cost_hash_receipt(code_sha_before="c", code_sha_after="c", data_sha_before="d", data_sha_after="d")["status"] == "PROVEN"
    assert cost_hash_receipt(code_sha_before="c", code_sha_after="c", data_sha_before="d", data_sha_after="x")["status"] == "REJECTED"


def test_hvr_0899_forward_is_after_cutoff():
    assert cost_forward_cutoff_receipt(forward_ts_ms=101, cutoff_ts_ms=100)["status"] == "PROVEN"
    assert cost_forward_cutoff_receipt(forward_ts_ms=100, cutoff_ts_ms=100)["status"] == "REJECTED"


def test_hvr_0900_pessimistic_costs_can_erase_edge():
    assert cost_pessimistic_edge_receipt(gross_edge=10, slippage=2, fees=1)["status"] == "PROVEN"
    assert cost_pessimistic_edge_receipt(gross_edge=2, slippage=2, fees=1)["status"] == "REJECTED"
