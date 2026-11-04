from hl_observer.simulation.capital_accounting import (
    CapitalAccountingTracker,
    capital_accounting_safety_receipt,
    capital_age_receipt,
    capital_balance_receipt,
    capital_commit_receipt,
    capital_concurrent_write_receipt,
    capital_conversion_receipt,
    capital_cutoff_receipt,
    capital_duplicate_receipt,
    capital_field_type_receipt,
    capital_fill_duplicate_receipt,
    capital_finite_receipt,
    capital_funding_sign_receipt,
    capital_mark_liquidability_receipt,
    capital_null_field_receipt,
    capital_partial_close_receipt,
    capital_rejection_no_debit_receipt,
    capital_replay_receipt,
    capital_required_field_receipt,
    capital_retry_receipt,
    capital_total_close_release_receipt,
)


def _snapshot():
    return CapitalAccountingTracker(starting_equity_usd=1000.0).observe(
        collateral_cash_usd=1000.0,
        positions=(),
        realized_pnl_usd=0.0,
        turnover_usd=0.0,
    )


def test_hvr_0621_capital_accounting_baseline_is_safe():
    assert capital_accounting_safety_receipt(_snapshot())["status"] == "PROVEN"
    assert capital_accounting_safety_receipt(object())["status"] == "REJECTED"


def test_hvr_0622_required_field():
    assert capital_required_field_receipt({"coin": "BTC"}, field="coin")["status"] == "PROVEN"
    assert capital_required_field_receipt({}, field="coin")["status"] == "REJECTED"


def test_hvr_0623_null_field():
    assert capital_null_field_receipt({"coin": "BTC"}, field="coin")["status"] == "PROVEN"
    assert capital_null_field_receipt({"coin": None}, field="coin")["status"] == "REJECTED"


def test_hvr_0624_field_type():
    assert capital_field_type_receipt({"depth": 1.0}, field="depth", expected_type=float)["status"] == "PROVEN"
    assert capital_field_type_receipt({"depth": "1"}, field="depth", expected_type=float)["status"] == "REJECTED"


def test_hvr_0625_finite_value():
    assert capital_finite_receipt(1.5)["status"] == "PROVEN"
    assert capital_finite_receipt(float("nan"))["status"] == "REJECTED"


def test_hvr_0626_cutoff():
    assert capital_cutoff_receipt(event_ts_ms=10, cutoff_ts_ms=10)["status"] == "PROVEN"
    assert capital_cutoff_receipt(event_ts_ms=11, cutoff_ts_ms=10)["status"] == "REJECTED"


def test_hvr_0627_age():
    assert capital_age_receipt(event_ts_ms=10, oldest_allowed_ts_ms=10)["status"] == "PROVEN"
    assert capital_age_receipt(event_ts_ms=9, oldest_allowed_ts_ms=10)["status"] == "REJECTED"


def test_hvr_0628_duplicate_events():
    assert capital_duplicate_receipt(event_ids=["a", "b"])["status"] == "PROVEN"
    assert capital_duplicate_receipt(event_ids=["a", "a"])["status"] == "REJECTED"


def test_hvr_0629_bounded_retry_requires_checkpoint():
    assert capital_retry_receipt(attempts=2, max_attempts=3, checkpoint_saved=True)["status"] == "PROVEN"
    assert capital_retry_receipt(attempts=4, max_attempts=3, checkpoint_saved=True)["status"] == "REJECTED"


def test_hvr_0630_replay_is_deterministic():
    assert capital_replay_receipt(outputs=[{"equity": 1000}, {"equity": 1000}])["status"] == "PROVEN"
    assert capital_replay_receipt(outputs=[{"equity": 1000}, {"equity": 999}])["status"] == "REJECTED"


def test_hvr_0631_fills_are_unique():
    assert capital_fill_duplicate_receipt(fill_ids=["fill-a", "fill-b"])["status"] == "PROVEN"
    assert capital_fill_duplicate_receipt(fill_ids=["fill-a", "fill-a"])["status"] == "REJECTED"


def test_hvr_0632_rejected_fill_does_not_debit_funds():
    assert capital_rejection_no_debit_receipt(rejected=True, debited=False)["status"] == "PROVEN"
    assert capital_rejection_no_debit_receipt(rejected=True, debited=True)["status"] == "REJECTED"


def test_hvr_0633_partial_close_has_explicit_cost():
    assert capital_partial_close_receipt(close_quantity=1.0, open_quantity=2.0, fee_known=True, fee_amount=0.0)["status"] == "PROVEN"
    assert capital_partial_close_receipt(close_quantity=1.0, open_quantity=2.0, fee_known=False, fee_amount=0.0)["status"] == "REJECTED"


def test_hvr_0634_total_close_releases_margin():
    assert capital_total_close_release_receipt(close_quantity=2.0, open_quantity=2.0, released_margin=10.0)["status"] == "PROVEN"
    assert capital_total_close_release_receipt(close_quantity=2.0, open_quantity=2.0, released_margin=-1.0)["status"] == "REJECTED"


def test_hvr_0635_mark_must_be_liquidable():
    assert capital_mark_liquidability_receipt(mark_price=100.0, bid=99.0, ask=101.0)["status"] == "PROVEN"
    assert capital_mark_liquidability_receipt(mark_price=None, bid=99.0, ask=101.0)["status"] == "REJECTED"


def test_hvr_0636_balance_cannot_be_negative():
    assert capital_balance_receipt(balance=0.0)["status"] == "PROVEN"
    assert capital_balance_receipt(balance=-0.1)["status"] == "REJECTED"


def test_hvr_0637_funding_sign_is_explicit():
    assert capital_funding_sign_receipt(amount=1.0, direction="CREDIT")["status"] == "PROVEN"
    assert capital_funding_sign_receipt(amount=1.0, direction="DEBIT")["status"] == "REJECTED"


def test_hvr_0638_conversion_requires_rate():
    assert capital_conversion_receipt(fee_amount=1.0, fee_token="USDC", pnl_currency="USD", token_to_pnl_rate=1.0)["status"] == "PROVEN"
    assert capital_conversion_receipt(fee_amount=1.0, fee_token="USDC", pnl_currency="USD", token_to_pnl_rate=None)["status"] == "REJECTED"


def test_hvr_0639_crash_before_commit_is_recoverable():
    assert capital_commit_receipt(crashed=True, committed=False, checkpoint_saved=True)["status"] == "PROVEN"
    assert capital_commit_receipt(crashed=True, committed=True, checkpoint_saved=False)["status"] == "REJECTED"


def test_hvr_0640_concurrent_writes_are_unique():
    assert capital_concurrent_write_receipt(write_ids=["w1", "w2"])["status"] == "PROVEN"
    assert capital_concurrent_write_receipt(write_ids=["w1", "w1"])["status"] == "REJECTED"
