from hl_observer.simulation.economic_freeze_registry import (
    SCHEMA,
    economic_freeze_safety_receipt,
    freeze_age_receipt,
    freeze_cutoff_receipt,
    freeze_duplicate_receipt,
    freeze_effect_size_receipt,
    freeze_embargo_receipt,
    freeze_field_type_receipt,
    freeze_fill_duplicate_receipt,
    freeze_finite_receipt,
    freeze_forward_cutoff_receipt,
    freeze_hash_receipt,
    freeze_holdout_receipt,
    freeze_null_field_receipt,
    freeze_partition_receipt,
    freeze_pessimistic_edge_receipt,
    freeze_replay_receipt,
    freeze_required_field_receipt,
    freeze_retry_receipt,
    freeze_trials_receipt,
    freeze_wallet_independence_receipt,
)


def _freeze():
    return {
        "schema_version": SCHEMA,
        "family": "COPY_VAULT",
        "freeze_hash": "f" * 64,
        "data_sha256": "d" * 64,
        "config_sha256": "c" * 64,
        "parameters_sha256": "p" * 64,
        "frozen_at_ms": 100,
        "paper_only": True,
        "real_execution": False,
    }


def test_hvr_0821_economic_freeze_baseline_is_safe():
    assert economic_freeze_safety_receipt(_freeze())["status"] == "PROVEN"
    assert economic_freeze_safety_receipt({})["status"] == "REJECTED"


def test_hvr_0822_required_field():
    assert freeze_required_field_receipt({"coin": "BTC"}, field="coin")["status"] == "PROVEN"
    assert freeze_required_field_receipt({}, field="coin")["status"] == "REJECTED"


def test_hvr_0823_null_field():
    assert freeze_null_field_receipt({"coin": "BTC"}, field="coin")["status"] == "PROVEN"
    assert freeze_null_field_receipt({"coin": None}, field="coin")["status"] == "REJECTED"


def test_hvr_0824_field_type():
    assert freeze_field_type_receipt({"depth": 1.0}, field="depth", expected_type=float)["status"] == "PROVEN"
    assert freeze_field_type_receipt({"depth": "1"}, field="depth", expected_type=float)["status"] == "REJECTED"


def test_hvr_0825_finite_value():
    assert freeze_finite_receipt(1.5)["status"] == "PROVEN"
    assert freeze_finite_receipt(float("nan"))["status"] == "REJECTED"


def test_hvr_0826_cutoff():
    assert freeze_cutoff_receipt(event_ts_ms=10, cutoff_ts_ms=10)["status"] == "PROVEN"
    assert freeze_cutoff_receipt(event_ts_ms=11, cutoff_ts_ms=10)["status"] == "REJECTED"


def test_hvr_0827_age():
    assert freeze_age_receipt(event_ts_ms=10, oldest_allowed_ts_ms=10)["status"] == "PROVEN"
    assert freeze_age_receipt(event_ts_ms=9, oldest_allowed_ts_ms=10)["status"] == "REJECTED"


def test_hvr_0828_duplicate_events():
    assert freeze_duplicate_receipt(event_ids=["a", "b"])["status"] == "PROVEN"
    assert freeze_duplicate_receipt(event_ids=["a", "a"])["status"] == "REJECTED"


def test_hvr_0829_bounded_retry_requires_checkpoint():
    assert freeze_retry_receipt(attempts=2, max_attempts=3, checkpoint_saved=True)["status"] == "PROVEN"
    assert freeze_retry_receipt(attempts=4, max_attempts=3, checkpoint_saved=True)["status"] == "REJECTED"


def test_hvr_0830_replay_is_deterministic():
    assert freeze_replay_receipt(outputs=[{"equity": 1000}, {"equity": 1000}])["status"] == "PROVEN"
    assert freeze_replay_receipt(outputs=[{"equity": 1000}, {"equity": 999}])["status"] == "REJECTED"


def test_hvr_0831_train_oos_forward_are_disjoint():
    assert freeze_partition_receipt(train_ids=["t1"], oos_ids=["o1"], forward_ids=["f1"])["status"] == "PROVEN"
    assert freeze_partition_receipt(train_ids=["t1"], oos_ids=["t1"], forward_ids=["f1"])["status"] == "REJECTED"


def test_hvr_0832_holdout_is_not_used_for_tuning():
    assert freeze_holdout_receipt(tuned_on_holdout=False, holdout_locked=True)["status"] == "PROVEN"
    assert freeze_holdout_receipt(tuned_on_holdout=True, holdout_locked=False)["status"] == "REJECTED"


def test_hvr_0833_embargo_is_sufficient():
    assert freeze_embargo_receipt(gap_ms=100, required_gap_ms=50)["status"] == "PROVEN"
    assert freeze_embargo_receipt(gap_ms=10, required_gap_ms=50)["status"] == "REJECTED"


def test_hvr_0834_trials_are_recorded():
    assert freeze_trials_receipt(trials=3, recorded_trials=3)["status"] == "PROVEN"
    assert freeze_trials_receipt(trials=3, recorded_trials=2)["status"] == "REJECTED"


def test_hvr_0835_effect_is_not_single_trade():
    assert freeze_effect_size_receipt(trade_count=10, gain=1.0, minimum_trades=2)["status"] == "PROVEN"
    assert freeze_effect_size_receipt(trade_count=1, gain=1.0, minimum_trades=2)["status"] == "REJECTED"


def test_hvr_0836_wallets_are_independent():
    assert freeze_wallet_independence_receipt(wallet_ids=["w1", "w2"], max_correlation=0.5)["status"] == "PROVEN"
    assert freeze_wallet_independence_receipt(wallet_ids=["w1", "w1"], max_correlation=0.5)["status"] == "REJECTED"


def test_hvr_0837_code_sha_does_not_change_after_freeze():
    assert freeze_hash_receipt(code_sha_before="c", code_sha_after="c", data_sha_before="d", data_sha_after="d")["status"] == "PROVEN"
    assert freeze_hash_receipt(code_sha_before="c", code_sha_after="x", data_sha_before="d", data_sha_after="d")["status"] == "REJECTED"


def test_hvr_0838_data_sha_does_not_change_after_freeze():
    assert freeze_hash_receipt(code_sha_before="c", code_sha_after="c", data_sha_before="d", data_sha_after="d")["status"] == "PROVEN"
    assert freeze_hash_receipt(code_sha_before="c", code_sha_after="c", data_sha_before="d", data_sha_after="x")["status"] == "REJECTED"


def test_hvr_0839_forward_is_after_cutoff():
    assert freeze_forward_cutoff_receipt(forward_ts_ms=101, cutoff_ts_ms=100)["status"] == "PROVEN"
    assert freeze_forward_cutoff_receipt(forward_ts_ms=99, cutoff_ts_ms=100)["status"] == "REJECTED"


def test_hvr_0840_slippage_and_fees_do_not_erase_edge():
    assert freeze_pessimistic_edge_receipt(gross_edge=10.0, slippage=2.0, fees=1.0)["status"] == "PROVEN"
    assert freeze_pessimistic_edge_receipt(gross_edge=2.0, slippage=2.0, fees=1.0)["status"] == "REJECTED"
    assert freeze_fill_duplicate_receipt(fill_ids=["f1", "f2"])["status"] == "PROVEN"
