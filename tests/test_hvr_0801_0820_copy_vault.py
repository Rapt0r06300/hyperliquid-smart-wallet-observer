from hl_observer.backtest.walk_forward import (
    split_walk_forward,
    walk_age_receipt,
    walk_cutoff_receipt,
    walk_duplicate_receipt,
    walk_field_type_receipt,
    walk_finite_receipt,
    walk_fill_duplicate_receipt,
    walk_forward_effect_size_receipt,
    walk_forward_embargo_receipt,
    walk_forward_forward_cutoff_receipt,
    walk_forward_freeze_receipt,
    walk_forward_holdout_receipt,
    walk_forward_partition_receipt,
    walk_forward_pessimistic_edge_receipt,
    walk_forward_safety_receipt,
    walk_forward_trials_receipt,
    walk_forward_wallet_independence_receipt,
    walk_null_field_receipt,
    walk_replay_receipt,
    walk_required_field_receipt,
    walk_retry_receipt,
)


def _report():
    return {
        "train": ["t1"], "oos": ["o1"], "forward": ["f1"],
        "code_sha": "code-a", "data_sha": "data-a", "cutoff_ts_ms": 100, "trials": 3,
    }


def test_hvr_0801_walk_forward_baseline_is_safe():
    assert walk_forward_safety_receipt(_report())["status"] == "PROVEN"
    assert walk_forward_safety_receipt({})["status"] == "REJECTED"
    assert split_walk_forward([1, 2, 3, 4], 0.5) == ([1, 2], [3, 4])


def test_hvr_0802_required_field():
    assert walk_required_field_receipt({"coin": "BTC"}, field="coin")["status"] == "PROVEN"
    assert walk_required_field_receipt({}, field="coin")["status"] == "REJECTED"


def test_hvr_0803_null_field():
    assert walk_null_field_receipt({"coin": "BTC"}, field="coin")["status"] == "PROVEN"
    assert walk_null_field_receipt({"coin": None}, field="coin")["status"] == "REJECTED"


def test_hvr_0804_field_type():
    assert walk_field_type_receipt({"depth": 1.0}, field="depth", expected_type=float)["status"] == "PROVEN"
    assert walk_field_type_receipt({"depth": "1"}, field="depth", expected_type=float)["status"] == "REJECTED"


def test_hvr_0805_finite_value():
    assert walk_finite_receipt(1.5)["status"] == "PROVEN"
    assert walk_finite_receipt(float("nan"))["status"] == "REJECTED"


def test_hvr_0806_cutoff():
    assert walk_cutoff_receipt(event_ts_ms=10, cutoff_ts_ms=10)["status"] == "PROVEN"
    assert walk_cutoff_receipt(event_ts_ms=11, cutoff_ts_ms=10)["status"] == "REJECTED"


def test_hvr_0807_age():
    assert walk_age_receipt(event_ts_ms=10, oldest_allowed_ts_ms=10)["status"] == "PROVEN"
    assert walk_age_receipt(event_ts_ms=9, oldest_allowed_ts_ms=10)["status"] == "REJECTED"


def test_hvr_0808_duplicate_events():
    assert walk_duplicate_receipt(event_ids=["a", "b"])["status"] == "PROVEN"
    assert walk_duplicate_receipt(event_ids=["a", "a"])["status"] == "REJECTED"


def test_hvr_0809_bounded_retry_requires_checkpoint():
    assert walk_retry_receipt(attempts=2, max_attempts=3, checkpoint_saved=True)["status"] == "PROVEN"
    assert walk_retry_receipt(attempts=4, max_attempts=3, checkpoint_saved=True)["status"] == "REJECTED"


def test_hvr_0810_replay_is_deterministic():
    assert walk_replay_receipt(outputs=[{"equity": 1000}, {"equity": 1000}])["status"] == "PROVEN"
    assert walk_replay_receipt(outputs=[{"equity": 1000}, {"equity": 999}])["status"] == "REJECTED"


def test_hvr_0811_train_oos_forward_are_disjoint():
    assert walk_forward_partition_receipt(train_ids=["t1"], oos_ids=["o1"], forward_ids=["f1"])["status"] == "PROVEN"
    assert walk_forward_partition_receipt(train_ids=["t1"], oos_ids=["t1"], forward_ids=["f1"])["status"] == "REJECTED"


def test_hvr_0812_holdout_is_not_used_for_tuning():
    assert walk_forward_holdout_receipt(tuned_on_holdout=False, holdout_locked=True)["status"] == "PROVEN"
    assert walk_forward_holdout_receipt(tuned_on_holdout=True, holdout_locked=False)["status"] == "REJECTED"


def test_hvr_0813_embargo_is_sufficient():
    assert walk_forward_embargo_receipt(gap_ms=100, required_gap_ms=50)["status"] == "PROVEN"
    assert walk_forward_embargo_receipt(gap_ms=10, required_gap_ms=50)["status"] == "REJECTED"


def test_hvr_0814_trials_are_recorded():
    assert walk_forward_trials_receipt(trials=3, recorded_trials=3)["status"] == "PROVEN"
    assert walk_forward_trials_receipt(trials=3, recorded_trials=2)["status"] == "REJECTED"


def test_hvr_0815_effect_is_not_single_trade():
    assert walk_forward_effect_size_receipt(trade_count=10, gain=1.0, minimum_trades=2)["status"] == "PROVEN"
    assert walk_forward_effect_size_receipt(trade_count=1, gain=1.0, minimum_trades=2)["status"] == "REJECTED"


def test_hvr_0816_wallets_are_independent():
    assert walk_forward_wallet_independence_receipt(wallet_ids=["w1", "w2"], max_correlation=0.5)["status"] == "PROVEN"
    assert walk_forward_wallet_independence_receipt(wallet_ids=["w1", "w1"], max_correlation=0.5)["status"] == "REJECTED"


def test_hvr_0817_code_sha_does_not_change_after_freeze():
    assert walk_forward_freeze_receipt(code_sha_before="c", code_sha_after="c", data_sha_before="d", data_sha_after="d")["status"] == "PROVEN"
    assert walk_forward_freeze_receipt(code_sha_before="c", code_sha_after="x", data_sha_before="d", data_sha_after="d")["status"] == "REJECTED"


def test_hvr_0818_data_sha_does_not_change_after_freeze():
    assert walk_forward_freeze_receipt(code_sha_before="c", code_sha_after="c", data_sha_before="d", data_sha_after="d")["status"] == "PROVEN"
    assert walk_forward_freeze_receipt(code_sha_before="c", code_sha_after="c", data_sha_before="d", data_sha_after="x")["status"] == "REJECTED"


def test_hvr_0819_forward_is_after_cutoff():
    assert walk_forward_forward_cutoff_receipt(forward_ts_ms=101, cutoff_ts_ms=100)["status"] == "PROVEN"
    assert walk_forward_forward_cutoff_receipt(forward_ts_ms=99, cutoff_ts_ms=100)["status"] == "REJECTED"


def test_hvr_0820_slippage_and_fees_do_not_erase_edge():
    assert walk_forward_pessimistic_edge_receipt(gross_edge=10.0, slippage=2.0, fees=1.0)["status"] == "PROVEN"
    assert walk_forward_pessimistic_edge_receipt(gross_edge=2.0, slippage=2.0, fees=1.0)["status"] == "REJECTED"
    assert walk_fill_duplicate_receipt(fill_ids=["f1", "f2"])["status"] == "PROVEN"
