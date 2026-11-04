from hl_observer.simulation.accounting_truth import (
    accounting_age_receipt,
    accounting_balance_receipt,
    accounting_commit_receipt,
    accounting_concurrent_write_receipt,
    accounting_conversion_receipt,
    accounting_cutoff_receipt,
    accounting_duplicate_receipt,
    accounting_field_type_receipt,
    accounting_fill_duplicate_receipt,
    accounting_finite_receipt,
    accounting_funding_sign_receipt,
    accounting_mark_liquidability_receipt,
    accounting_null_field_receipt,
    accounting_partial_close_receipt,
    accounting_rejection_no_debit_receipt,
    accounting_replay_receipt,
    accounting_required_field_receipt,
    accounting_retry_receipt,
    accounting_total_close_release_receipt,
    accounting_truth_safety_receipt,
)


def test_hvr_0601_accounting_truth_baseline_is_safe():
    assert accounting_truth_safety_receipt({"paper_read_only": True, "real_execution": False})["status"] == "PROVEN"
    assert accounting_truth_safety_receipt({"paper_read_only": False, "real_execution": True})["status"] == "REJECTED"


def test_hvr_0602_required_field():
    assert accounting_required_field_receipt({"coin": "BTC"}, field="coin")["status"] == "PROVEN"
    assert accounting_required_field_receipt({}, field="coin")["status"] == "REJECTED"


def test_hvr_0603_null_field():
    assert accounting_null_field_receipt({"coin": "BTC"}, field="coin")["status"] == "PROVEN"
    assert accounting_null_field_receipt({"coin": None}, field="coin")["status"] == "REJECTED"


def test_hvr_0604_field_type():
    assert accounting_field_type_receipt({"depth": 1.0}, field="depth", expected_type=float)["status"] == "PROVEN"
    assert accounting_field_type_receipt({"depth": "1"}, field="depth", expected_type=float)["status"] == "REJECTED"


def test_hvr_0605_finite_value():
    assert accounting_finite_receipt(1.5)["status"] == "PROVEN"
    assert accounting_finite_receipt(float("nan"))["status"] == "REJECTED"


def test_hvr_0606_cutoff():
    assert accounting_cutoff_receipt(event_ts_ms=10, cutoff_ts_ms=10)["status"] == "PROVEN"
    assert accounting_cutoff_receipt(event_ts_ms=11, cutoff_ts_ms=10)["status"] == "REJECTED"


def test_hvr_0607_age():
    assert accounting_age_receipt(event_ts_ms=10, oldest_allowed_ts_ms=10)["status"] == "PROVEN"
    assert accounting_age_receipt(event_ts_ms=9, oldest_allowed_ts_ms=10)["status"] == "REJECTED"


def test_hvr_0608_duplicate_events():
    assert accounting_duplicate_receipt(event_ids=["a", "b"])["status"] == "PROVEN"
    assert accounting_duplicate_receipt(event_ids=["a", "a"])["status"] == "REJECTED"


def test_hvr_0609_bounded_retry_requires_checkpoint():
    assert accounting_retry_receipt(attempts=2, max_attempts=3, checkpoint_saved=True)["status"] == "PROVEN"
    assert accounting_retry_receipt(attempts=4, max_attempts=3, checkpoint_saved=True)["status"] == "REJECTED"


def test_hvr_0610_replay_is_deterministic():
    assert accounting_replay_receipt(outputs=[{"pnl": 1}, {"pnl": 1}])["status"] == "PROVEN"
    assert accounting_replay_receipt(outputs=[{"pnl": 1}, {"pnl": 2}])["status"] == "REJECTED"


def test_hvr_0611_fills_are_unique():
    assert accounting_fill_duplicate_receipt(fill_ids=["fill-a", "fill-b"])["status"] == "PROVEN"
    assert accounting_fill_duplicate_receipt(fill_ids=["fill-a", "fill-a"])["status"] == "REJECTED"


def test_hvr_0612_rejected_fill_does_not_debit_funds():
    assert accounting_rejection_no_debit_receipt(rejected=True, debited=False)["status"] == "PROVEN"
    assert accounting_rejection_no_debit_receipt(rejected=True, debited=True)["status"] == "REJECTED"


def test_hvr_0613_partial_close_has_explicit_cost():
    assert accounting_partial_close_receipt(close_quantity=1.0, open_quantity=2.0, fee_known=True, fee_amount=0.0)["status"] == "PROVEN"
    assert accounting_partial_close_receipt(close_quantity=1.0, open_quantity=2.0, fee_known=False, fee_amount=0.0)["status"] == "REJECTED"


def test_hvr_0614_total_close_releases_margin():
    assert accounting_total_close_release_receipt(close_quantity=2.0, open_quantity=2.0, released_margin=10.0)["status"] == "PROVEN"
    assert accounting_total_close_release_receipt(close_quantity=2.0, open_quantity=2.0, released_margin=-1.0)["status"] == "REJECTED"


def test_hvr_0615_mark_must_be_liquidable():
    assert accounting_mark_liquidability_receipt(mark_price=100.0, bid=99.0, ask=101.0)["status"] == "PROVEN"
    assert accounting_mark_liquidability_receipt(mark_price=None, bid=99.0, ask=101.0)["status"] == "REJECTED"


def test_hvr_0616_balance_cannot_be_negative():
    assert accounting_balance_receipt(balance=0.0)["status"] == "PROVEN"
    assert accounting_balance_receipt(balance=-0.1)["status"] == "REJECTED"


def test_hvr_0617_funding_sign_is_explicit():
    assert accounting_funding_sign_receipt(amount=1.0, direction="CREDIT")["status"] == "PROVEN"
    assert accounting_funding_sign_receipt(amount=1.0, direction="DEBIT")["status"] == "REJECTED"


def test_hvr_0618_conversion_requires_rate():
    assert accounting_conversion_receipt(fee_amount=1.0, fee_token="USDC", pnl_currency="USD", token_to_pnl_rate=1.0)["status"] == "PROVEN"
    assert accounting_conversion_receipt(fee_amount=1.0, fee_token="USDC", pnl_currency="USD", token_to_pnl_rate=None)["status"] == "REJECTED"


def test_hvr_0619_crash_before_commit_is_recoverable():
    assert accounting_commit_receipt(crashed=True, committed=False, checkpoint_saved=True)["status"] == "PROVEN"
    assert accounting_commit_receipt(crashed=True, committed=True, checkpoint_saved=False)["status"] == "REJECTED"


def test_hvr_0620_concurrent_writes_are_unique():
    assert accounting_concurrent_write_receipt(write_ids=["w1", "w2"])["status"] == "PROVEN"
    assert accounting_concurrent_write_receipt(write_ids=["w1", "w1"])["status"] == "REJECTED"
