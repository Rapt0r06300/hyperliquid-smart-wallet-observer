from hl_observer.backtesting.copy_vault_replay_controls import (
    champion_code_freeze_receipt,
    champion_dataset_freeze_receipt,
    cost_model_freeze_receipt,
    forward_maturity_receipt,
    holdout_hyperparam_receipt,
    leader_selection_receipt,
    multiple_testing_receipt,
    oos_selection_timing_receipt,
    purged_window_receipt,
    wallet_disjointness_receipt,
)


SHA_A = "a" * 40


def test_bug_281_oos_selection_precedes_outcome():
    assert oos_selection_timing_receipt(selection_ts_ms=10, outcome_ts_ms=20, oos_start_ts_ms=10)["status"] == "PROVEN"


def test_bug_282_purged_windows_are_disjoint():
    assert purged_window_receipt(train_intervals=[(0, 10)], test_intervals=[(20, 30)], horizon_ms=5)["status"] == "PROVEN"


def test_bug_283_leader_selection_is_causal():
    assert leader_selection_receipt(leader_selection_ts_ms=10, leader_observation_cutoff_ms=20, pnl_cutoff_ms=30)["status"] == "PROVEN"


def test_bug_284_trials_are_corrected():
    assert multiple_testing_receipt(trial_count=10, correction_method="holm", adjusted_alpha=0.01)["status"] == "PROVEN"


def test_bug_285_code_sha_is_frozen():
    assert champion_code_freeze_receipt(champion_sha=SHA_A, evaluated_sha=SHA_A, frozen=True)["status"] == "PROVEN"


def test_bug_286_dataset_hash_is_frozen():
    assert champion_dataset_freeze_receipt(dataset_hash=SHA_A, evaluated_dataset_hash=SHA_A, frozen=True)["status"] == "PROVEN"


def test_bug_287_cost_model_is_frozen():
    assert cost_model_freeze_receipt(cost_model_hash=SHA_A, evaluated_cost_model_hash=SHA_A, frozen=True)["status"] == "PROVEN"


def test_bug_288_forward_window_is_mature():
    assert forward_maturity_receipt(freeze_ts_ms=100, forward_end_ts_ms=200, minimum_duration_ms=50)["status"] == "PROVEN"


def test_bug_289_wallet_reuse_is_analyzed():
    assert wallet_disjointness_receipt(train_wallets=["w1"], oos_wallets=["w1"], overlap_analysis=True)["status"] == "PROVEN"


def test_bug_290_holdout_is_not_used_for_tuning():
    assert holdout_hyperparam_receipt(tuning_cutoff_ms=10, holdout_cutoff_ms=20, tuned_after_holdout=False)["status"] == "PROVEN"
