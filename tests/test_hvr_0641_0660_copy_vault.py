from hl_observer.simulation.paper_ledger import (
    PaperLedger,
    ledger_age_receipt,
    ledger_balance_receipt,
    ledger_commit_receipt,
    ledger_concurrent_write_receipt,
    ledger_conversion_receipt,
    ledger_cutoff_receipt,
    ledger_duplicate_receipt,
    ledger_field_type_receipt,
    ledger_fill_duplicate_receipt,
    ledger_finite_receipt,
    ledger_funding_sign_receipt,
    ledger_mark_liquidability_receipt,
    ledger_null_field_receipt,
    ledger_partial_close_receipt,
    ledger_rejection_no_debit_receipt,
    ledger_replay_receipt,
    ledger_required_field_receipt,
    ledger_retry_receipt,
    ledger_total_close_release_receipt,
    paper_ledger_safety_receipt,
)


def test_hvr_0641_paper_ledger_baseline_is_safe():
    assert paper_ledger_safety_receipt(PaperLedger())["status"] == "PROVEN"
    assert paper_ledger_safety_receipt(object())["status"] == "REJECTED"


def test_hvr_0642_required_field():
    assert ledger_required_field_receipt({"coin": "BTC"}, field="coin")["status"] == "PROVEN"
    assert ledger_required_field_receipt({}, field="coin")["status"] == "REJECTED"


def test_hvr_0643_null_field():
    assert ledger_null_field_receipt({"coin": "BTC"}, field="coin")["status"] == "PROVEN"
    assert ledger_null_field_receipt({"coin": None}, field="coin")["status"] == "REJECTED"


def test_hvr_0644_field_type():
    assert ledger_field_type_receipt({"depth": 1.0}, field="depth", expected_type=float)["status"] == "PROVEN"
    assert ledger_field_type_receipt({"depth": "1"}, field="depth", expected_type=float)["status"] == "REJECTED"


def test_hvr_0645_finite_value():
    assert ledger_finite_receipt(1.5)["status"] == "PROVEN"
    assert ledger_finite_receipt(float("nan"))["status"] == "REJECTED"


def test_hvr_0646_cutoff():
    assert ledger_cutoff_receipt(event_ts_ms=10, cutoff_ts_ms=10)["status"] == "PROVEN"
    assert ledger_cutoff_receipt(event_ts_ms=11, cutoff_ts_ms=10)["status"] == "REJECTED"


def test_hvr_0647_age():
    assert ledger_age_receipt(event_ts_ms=10, oldest_allowed_ts_ms=10)["status"] == "PROVEN"
    assert ledger_age_receipt(event_ts_ms=9, oldest_allowed_ts_ms=10)["status"] == "REJECTED"


def test_hvr_0648_duplicate_events():
    assert ledger_duplicate_receipt(event_ids=["a", "b"])["status"] == "PROVEN"
    assert ledger_duplicate_receipt(event_ids=["a", "a"])["status"] == "REJECTED"


def test_hvr_0649_bounded_retry_requires_checkpoint():
    assert ledger_retry_receipt(attempts=2, max_attempts=3, checkpoint_saved=True)["status"] == "PROVEN"
    assert ledger_retry_receipt(attempts=4, max_attempts=3, checkpoint_saved=True)["status"] == "REJECTED"


def test_hvr_0650_replay_is_deterministic():
    assert ledger_replay_receipt(outputs=[{"equity": 1000}, {"equity": 1000}])["status"] == "PROVEN"
    assert ledger_replay_receipt(outputs=[{"equity": 1000}, {"equity": 999}])["status"] == "REJECTED"


def test_hvr_0651_fills_are_unique():
    assert ledger_fill_duplicate_receipt(fill_ids=["fill-a", "fill-b"])["status"] == "PROVEN"
    assert ledger_fill_duplicate_receipt(fill_ids=["fill-a", "fill-a"])["status"] == "REJECTED"


def test_hvr_0652_rejected_fill_does_not_debit_funds():
    assert ledger_rejection_no_debit_receipt(rejected=True, debited=False)["status"] == "PROVEN"
    assert ledger_rejection_no_debit_receipt(rejected=True, debited=True)["status"] == "REJECTED"


def test_hvr_0653_partial_close_has_explicit_cost():
    assert ledger_partial_close_receipt(close_quantity=1.0, open_quantity=2.0, fee_known=True, fee_amount=0.0)["status"] == "PROVEN"
    assert ledger_partial_close_receipt(close_quantity=1.0, open_quantity=2.0, fee_known=False, fee_amount=0.0)["status"] == "REJECTED"


def test_hvr_0654_total_close_releases_margin():
    assert ledger_total_close_release_receipt(close_quantity=2.0, open_quantity=2.0, released_margin=10.0)["status"] == "PROVEN"
    assert ledger_total_close_release_receipt(close_quantity=2.0, open_quantity=2.0, released_margin=-1.0)["status"] == "REJECTED"


def test_hvr_0655_mark_must_be_liquidable():
    assert ledger_mark_liquidability_receipt(mark_price=100.0, bid=99.0, ask=101.0)["status"] == "PROVEN"
    assert ledger_mark_liquidability_receipt(mark_price=None, bid=99.0, ask=101.0)["status"] == "REJECTED"


def test_hvr_0656_balance_cannot_be_negative():
    assert ledger_balance_receipt(balance=0.0)["status"] == "PROVEN"
    assert ledger_balance_receipt(balance=-0.1)["status"] == "REJECTED"


def test_hvr_0657_funding_sign_is_explicit():
    assert ledger_funding_sign_receipt(amount=1.0, direction="CREDIT")["status"] == "PROVEN"
    assert ledger_funding_sign_receipt(amount=1.0, direction="DEBIT")["status"] == "REJECTED"


def test_hvr_0658_conversion_requires_rate():
    assert ledger_conversion_receipt(fee_amount=1.0, fee_token="USDC", pnl_currency="USD", token_to_pnl_rate=1.0)["status"] == "PROVEN"
    assert ledger_conversion_receipt(fee_amount=1.0, fee_token="USDC", pnl_currency="USD", token_to_pnl_rate=None)["status"] == "REJECTED"


def test_hvr_0659_crash_before_commit_is_recoverable():
    assert ledger_commit_receipt(crashed=True, committed=False, checkpoint_saved=True)["status"] == "PROVEN"
    assert ledger_commit_receipt(crashed=True, committed=True, checkpoint_saved=False)["status"] == "REJECTED"


def test_hvr_0660_concurrent_writes_are_unique():
    assert ledger_concurrent_write_receipt(write_ids=["w1", "w2"])["status"] == "PROVEN"
    assert ledger_concurrent_write_receipt(write_ids=["w1", "w1"])["status"] == "REJECTED"
