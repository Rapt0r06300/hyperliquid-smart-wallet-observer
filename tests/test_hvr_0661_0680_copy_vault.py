from hl_observer.simulation.pnl_reconciliation import (
    pnl_age_receipt,
    pnl_balance_receipt,
    pnl_commit_receipt,
    pnl_concurrent_write_receipt,
    pnl_conversion_receipt,
    pnl_cutoff_receipt,
    pnl_done_receipt,
    pnl_duplicate_receipt,
    pnl_field_type_receipt,
    pnl_fill_duplicate_receipt,
    pnl_finite_receipt,
    pnl_funding_sign_receipt,
    pnl_mark_liquidability_receipt,
    pnl_null_field_receipt,
    pnl_partial_close_receipt,
    pnl_reconciliation_safety_receipt,
    pnl_rejection_no_debit_receipt,
    pnl_replay_receipt,
    pnl_required_field_receipt,
    pnl_retry_receipt,
    pnl_total_close_release_receipt,
    reconcile_pnl,
)


def _reconciliation():
    return reconcile_pnl(
        starting_balance_usdc=1000.0,
        realized_pnl_usdc=10.0,
        unrealized_pnl_usdc=5.0,
        fees_paid_usdc=1.0,
        funding_net_usdc=0.0,
        actual_equity_usdc=1014.0,
    )


def test_hvr_0661_pnl_reconciliation_baseline_is_safe():
    assert pnl_reconciliation_safety_receipt(_reconciliation())["status"] == "PROVEN"
    assert pnl_reconciliation_safety_receipt(object())["status"] == "REJECTED"


def test_hvr_0662_required_field():
    assert pnl_required_field_receipt({"coin": "BTC"}, field="coin")["status"] == "PROVEN"
    assert pnl_required_field_receipt({}, field="coin")["status"] == "REJECTED"


def test_hvr_0663_null_field():
    assert pnl_null_field_receipt({"coin": "BTC"}, field="coin")["status"] == "PROVEN"
    assert pnl_null_field_receipt({"coin": None}, field="coin")["status"] == "REJECTED"


def test_hvr_0664_field_type():
    assert pnl_field_type_receipt({"depth": 1.0}, field="depth", expected_type=float)["status"] == "PROVEN"
    assert pnl_field_type_receipt({"depth": "1"}, field="depth", expected_type=float)["status"] == "REJECTED"


def test_hvr_0665_finite_value():
    assert pnl_finite_receipt(1.5)["status"] == "PROVEN"
    assert pnl_finite_receipt(float("nan"))["status"] == "REJECTED"


def test_hvr_0666_cutoff():
    assert pnl_cutoff_receipt(event_ts_ms=10, cutoff_ts_ms=10)["status"] == "PROVEN"
    assert pnl_cutoff_receipt(event_ts_ms=11, cutoff_ts_ms=10)["status"] == "REJECTED"


def test_hvr_0667_age():
    assert pnl_age_receipt(event_ts_ms=10, oldest_allowed_ts_ms=10)["status"] == "PROVEN"
    assert pnl_age_receipt(event_ts_ms=9, oldest_allowed_ts_ms=10)["status"] == "REJECTED"


def test_hvr_0668_duplicate_events():
    assert pnl_duplicate_receipt(event_ids=["a", "b"])["status"] == "PROVEN"
    assert pnl_duplicate_receipt(event_ids=["a", "a"])["status"] == "REJECTED"


def test_hvr_0669_bounded_retry_requires_checkpoint():
    assert pnl_retry_receipt(attempts=2, max_attempts=3, checkpoint_saved=True)["status"] == "PROVEN"
    assert pnl_retry_receipt(attempts=4, max_attempts=3, checkpoint_saved=True)["status"] == "REJECTED"


def test_hvr_0670_replay_is_deterministic():
    assert pnl_replay_receipt(outputs=[{"pnl": 1}, {"pnl": 1}])["status"] == "PROVEN"
    assert pnl_replay_receipt(outputs=[{"pnl": 1}, {"pnl": 2}])["status"] == "REJECTED"


def test_hvr_0671_fills_are_unique():
    assert pnl_fill_duplicate_receipt(fill_ids=["fill-a", "fill-b"])["status"] == "PROVEN"
    assert pnl_fill_duplicate_receipt(fill_ids=["fill-a", "fill-a"])["status"] == "REJECTED"


def test_hvr_0672_rejected_fill_does_not_debit_funds():
    assert pnl_rejection_no_debit_receipt(rejected=True, debited=False)["status"] == "PROVEN"
    assert pnl_rejection_no_debit_receipt(rejected=True, debited=True)["status"] == "REJECTED"


def test_hvr_0673_partial_close_has_explicit_cost():
    assert pnl_partial_close_receipt(close_quantity=1.0, open_quantity=2.0, fee_known=True, fee_amount=0.0)["status"] == "PROVEN"
    assert pnl_partial_close_receipt(close_quantity=1.0, open_quantity=2.0, fee_known=False, fee_amount=0.0)["status"] == "REJECTED"


def test_hvr_0674_total_close_releases_margin():
    assert pnl_total_close_release_receipt(close_quantity=2.0, open_quantity=2.0, released_margin=10.0)["status"] == "PROVEN"
    assert pnl_total_close_release_receipt(close_quantity=2.0, open_quantity=2.0, released_margin=-1.0)["status"] == "REJECTED"


def test_hvr_0675_mark_must_be_liquidable():
    assert pnl_mark_liquidability_receipt(mark_price=100.0, bid=99.0, ask=101.0)["status"] == "PROVEN"
    assert pnl_mark_liquidability_receipt(mark_price=None, bid=99.0, ask=101.0)["status"] == "REJECTED"


def test_hvr_0676_balance_cannot_be_negative():
    assert pnl_balance_receipt(balance=0.0)["status"] == "PROVEN"
    assert pnl_balance_receipt(balance=-0.1)["status"] == "REJECTED"


def test_hvr_0677_funding_sign_is_explicit():
    assert pnl_funding_sign_receipt(amount=1.0, direction="CREDIT")["status"] == "PROVEN"
    assert pnl_funding_sign_receipt(amount=1.0, direction="DEBIT")["status"] == "REJECTED"


def test_hvr_0678_conversion_requires_rate():
    assert pnl_conversion_receipt(fee_amount=1.0, fee_token="USDC", pnl_currency="USD", token_to_pnl_rate=1.0)["status"] == "PROVEN"
    assert pnl_conversion_receipt(fee_amount=1.0, fee_token="USDC", pnl_currency="USD", token_to_pnl_rate=None)["status"] == "REJECTED"


def test_hvr_0679_crash_before_commit_is_recoverable():
    assert pnl_commit_receipt(crashed=True, committed=False, checkpoint_saved=True)["status"] == "PROVEN"
    assert pnl_commit_receipt(crashed=True, committed=True, checkpoint_saved=False)["status"] == "REJECTED"


def test_hvr_0680_concurrent_writes_are_unique():
    assert pnl_concurrent_write_receipt(write_ids=["w1", "w2"])["status"] == "PROVEN"
    assert pnl_concurrent_write_receipt(write_ids=["w1", "w1"])["status"] == "REJECTED"


def test_hvr_0681_pnl_done_requires_all_proven_gates():
    checks = [
        pnl_required_field_receipt({"coin": "BTC"}, field="coin"),
        pnl_replay_receipt(outputs=[{"pnl": 1.0}, {"pnl": 1.0}]),
        pnl_commit_receipt(crashed=False, committed=True, checkpoint_saved=False),
    ]
    assert pnl_done_receipt(checks=checks)["status"] == "PROVEN"
    assert pnl_done_receipt(checks=checks[:-1] + [{"status": "PROVEN"}])["status"] == "REJECTED"
