from hl_observer.simulation.scoreboard_promotion import (
    promotion_finale,
    score_age_receipt,
    score_cutoff_receipt,
    score_duplicate_receipt,
    score_effect_size_receipt,
    score_embargo_receipt,
    score_field_type_receipt,
    score_fill_duplicate_receipt,
    score_finite_receipt,
    score_forward_cutoff_receipt,
    score_hash_receipt,
    score_holdout_receipt,
    score_null_field_receipt,
    score_partition_receipt,
    score_pessimistic_edge_receipt,
    score_replay_receipt,
    score_required_field_receipt,
    score_retry_receipt,
    score_trials_receipt,
    score_wallet_independence_receipt,
    scoreboard_promotion_safety_receipt,
)


def test_hvr_0841_scoreboard_promotion_baseline_is_safe():
    assert scoreboard_promotion_safety_receipt(promotion_finale({}, None))["status"] == "PROVEN"
    assert scoreboard_promotion_safety_receipt({"promue": True, "paper_only": True, "real_execution": False})["status"] == "REJECTED"


def test_hvr_0842_required_field():
    assert score_required_field_receipt({"coin": "BTC"}, field="coin")["status"] == "PROVEN"
    assert score_required_field_receipt({}, field="coin")["status"] == "REJECTED"


def test_hvr_0843_null_field():
    assert score_null_field_receipt({"coin": "BTC"}, field="coin")["status"] == "PROVEN"
    assert score_null_field_receipt({"coin": None}, field="coin")["status"] == "REJECTED"


def test_hvr_0844_field_type():
    assert score_field_type_receipt({"depth": 1.0}, field="depth", expected_type=float)["status"] == "PROVEN"
    assert score_field_type_receipt({"depth": "1"}, field="depth", expected_type=float)["status"] == "REJECTED"


def test_hvr_0845_finite_value():
    assert score_finite_receipt(1.5)["status"] == "PROVEN"
    assert score_finite_receipt(float("nan"))["status"] == "REJECTED"


def test_hvr_0846_cutoff():
    assert score_cutoff_receipt(event_ts_ms=10, cutoff_ts_ms=10)["status"] == "PROVEN"
    assert score_cutoff_receipt(event_ts_ms=11, cutoff_ts_ms=10)["status"] == "REJECTED"


def test_hvr_0847_age():
    assert score_age_receipt(event_ts_ms=10, oldest_allowed_ts_ms=10)["status"] == "PROVEN"
    assert score_age_receipt(event_ts_ms=9, oldest_allowed_ts_ms=10)["status"] == "REJECTED"


def test_hvr_0848_duplicate_events():
    assert score_duplicate_receipt(event_ids=["a", "b"])["status"] == "PROVEN"
    assert score_duplicate_receipt(event_ids=["a", "a"])["status"] == "REJECTED"


def test_hvr_0849_bounded_retry_requires_checkpoint():
    assert score_retry_receipt(attempts=2, max_attempts=3, checkpoint_saved=True)["status"] == "PROVEN"
    assert score_retry_receipt(attempts=4, max_attempts=3, checkpoint_saved=True)["status"] == "REJECTED"


def test_hvr_0850_replay_is_deterministic():
    assert score_replay_receipt(outputs=[{"equity": 1000}, {"equity": 1000}])["status"] == "PROVEN"
    assert score_replay_receipt(outputs=[{"equity": 1000}, {"equity": 999}])["status"] == "REJECTED"


def test_hvr_0851_train_oos_forward_are_disjoint():
    assert score_partition_receipt(train_ids=["t1"], oos_ids=["o1"], forward_ids=["f1"])["status"] == "PROVEN"
    assert score_partition_receipt(train_ids=["t1"], oos_ids=["t1"], forward_ids=["f1"])["status"] == "REJECTED"


def test_hvr_0852_holdout_is_not_used_for_tuning():
    assert score_holdout_receipt(tuned_on_holdout=False, holdout_locked=True)["status"] == "PROVEN"
    assert score_holdout_receipt(tuned_on_holdout=True, holdout_locked=False)["status"] == "REJECTED"


def test_hvr_0853_embargo_is_sufficient():
    assert score_embargo_receipt(gap_ms=100, required_gap_ms=50)["status"] == "PROVEN"
    assert score_embargo_receipt(gap_ms=10, required_gap_ms=50)["status"] == "REJECTED"


def test_hvr_0854_trials_are_recorded():
    assert score_trials_receipt(trials=3, recorded_trials=3)["status"] == "PROVEN"
    assert score_trials_receipt(trials=3, recorded_trials=2)["status"] == "REJECTED"


def test_hvr_0855_effect_is_not_single_trade():
    assert score_effect_size_receipt(trade_count=10, gain=1.0, minimum_trades=2)["status"] == "PROVEN"
    assert score_effect_size_receipt(trade_count=1, gain=1.0, minimum_trades=2)["status"] == "REJECTED"


def test_hvr_0856_wallets_are_independent():
    assert score_wallet_independence_receipt(wallet_ids=["w1", "w2"], max_correlation=0.5)["status"] == "PROVEN"
    assert score_wallet_independence_receipt(wallet_ids=["w1", "w1"], max_correlation=0.5)["status"] == "REJECTED"


def test_hvr_0857_code_sha_does_not_change_after_freeze():
    assert score_hash_receipt(code_sha_before="c", code_sha_after="c", data_sha_before="d", data_sha_after="d")["status"] == "PROVEN"
    assert score_hash_receipt(code_sha_before="c", code_sha_after="x", data_sha_before="d", data_sha_after="d")["status"] == "REJECTED"


def test_hvr_0858_data_sha_does_not_change_after_freeze():
    assert score_hash_receipt(code_sha_before="c", code_sha_after="c", data_sha_before="d", data_sha_after="d")["status"] == "PROVEN"
    assert score_hash_receipt(code_sha_before="c", code_sha_after="c", data_sha_before="d", data_sha_after="x")["status"] == "REJECTED"


def test_hvr_0859_forward_is_after_cutoff():
    assert score_forward_cutoff_receipt(forward_ts_ms=101, cutoff_ts_ms=100)["status"] == "PROVEN"
    assert score_forward_cutoff_receipt(forward_ts_ms=99, cutoff_ts_ms=100)["status"] == "REJECTED"


def test_hvr_0860_slippage_and_fees_do_not_erase_edge():
    assert score_pessimistic_edge_receipt(gross_edge=10.0, slippage=2.0, fees=1.0)["status"] == "PROVEN"
    assert score_pessimistic_edge_receipt(gross_edge=2.0, slippage=2.0, fees=1.0)["status"] == "REJECTED"
    assert score_fill_duplicate_receipt(fill_ids=["f1", "f2"])["status"] == "PROVEN"
