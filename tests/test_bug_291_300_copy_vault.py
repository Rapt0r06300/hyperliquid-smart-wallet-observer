from hl_observer.backtesting.copy_vault_robustness_controls import (
    aggregate_result_receipt, cost_sweep_receipt, hindsight_budget_receipt,
    holdout_reuse_receipt, liquidation_closure_receipt, price_error_margin_receipt,
    regime_shift_stress_receipt, stop_loss_causality_receipt,
    survivorship_wallet_receipt, variance_disclosure_receipt,
)


def test_bug_291_aggregate_result():
    assert aggregate_result_receipt(trade_count=10, independent_episode_count=5, bootstrap_sample_count=100, aggregate_required=True)["status"] == "PROVEN"


def test_bug_292_budget_frozen_before_outcome():
    assert hindsight_budget_receipt(allocation_ts_ms=10, outcome_cutoff_ms=20, allocation_frozen=True)["status"] == "PROVEN"


def test_bug_293_gain_exceeds_price_error():
    assert price_error_margin_receipt(net_gain_usd=2.0, price_error_usd=0.5)["status"] == "PROVEN"


def test_bug_294_cost_sweep_has_adverse_case():
    assert cost_sweep_receipt(scenarios=[{"scenario": "base", "net_pnl_usd": 2.0}, {"scenario": "adverse", "net_pnl_usd": -1.0}])["status"] == "PROVEN"


def test_bug_295_variance_is_disclosed():
    assert variance_disclosure_receipt(values=[1.0, 2.0, 3.0], variance_reported=True)["status"] == "PROVEN"


def test_bug_296_exited_wallets_are_retained():
    assert survivorship_wallet_receipt(included_wallets=["w1"], exited_wallets=["w2"], leaderboard_includes_exited=True)["status"] == "PROVEN"


def test_bug_297_regimes_are_stressed():
    assert regime_shift_stress_receipt(available_regimes=["normal", "stress"], tested_regimes=["normal", "stress"], stress_loss_limit_usd=10.0)["status"] == "PROVEN"


def test_bug_298_stop_loss_is_causal():
    assert stop_loss_causality_receipt(trigger_ts_ms=20, observed_quote_ts_ms=10, outcome_ts_ms=30)["status"] == "PROVEN"


def test_bug_299_liquidation_is_closed():
    assert liquidation_closure_receipt(position_ids=["p1"], closed_position_ids=["p1"], liquidation_events=[{"position_id": "p1"}])["status"] == "PROVEN"


def test_bug_300_holdout_reuse_is_blocked():
    assert holdout_reuse_receipt(holdout_id="h1", consumed_holdout_ids=["h1"], reuse_blocked=True)["status"] == "PROVEN"
