from hl_observer.simulation.liquidatable_marks import (
    liquidatable_marks_report,
    liquidatable_marks_safety_receipt,
    marks_age_receipt,
    marks_balance_receipt,
    marks_commit_receipt,
    marks_concurrent_write_receipt,
    marks_conversion_receipt,
    marks_cutoff_receipt,
    marks_done_receipt,
    marks_duplicate_receipt,
    marks_field_type_receipt,
    marks_fill_duplicate_receipt,
    marks_finite_receipt,
    marks_funding_sign_receipt,
    marks_mark_liquidability_receipt,
    marks_null_field_receipt,
    marks_partial_close_receipt,
    marks_rejection_no_debit_receipt,
    marks_replay_receipt,
    marks_required_field_receipt,
    marks_retry_receipt,
    marks_total_close_release_receipt,
)


def _report():
    return liquidatable_marks_report(
        [{"position_id": "p1", "coin": "BTC", "side": "LONG"}],
        {"BTC": {"bid": 100.0, "ask": 101.0}},
    )


def test_hvr_0681_liquidatable_marks_baseline_is_safe():
    assert liquidatable_marks_safety_receipt(_report())["status"] == "PROVEN"
    assert liquidatable_marks_safety_receipt(object())["status"] == "REJECTED"


def test_hvr_0682_required_field():
    assert marks_required_field_receipt({"coin": "BTC"}, field="coin")["status"] == "PROVEN"
    assert marks_required_field_receipt({}, field="coin")["status"] == "REJECTED"


def test_hvr_0683_null_field():
    assert marks_null_field_receipt({"coin": "BTC"}, field="coin")["status"] == "PROVEN"
    assert marks_null_field_receipt({"coin": None}, field="coin")["status"] == "REJECTED"


def test_hvr_0684_field_type():
    assert marks_field_type_receipt({"depth": 1.0}, field="depth", expected_type=float)["status"] == "PROVEN"
    assert marks_field_type_receipt({"depth": "1"}, field="depth", expected_type=float)["status"] == "REJECTED"


def test_hvr_0685_finite_value():
    assert marks_finite_receipt(1.5)["status"] == "PROVEN"
    assert marks_finite_receipt(float("nan"))["status"] == "REJECTED"


def test_hvr_0686_cutoff():
    assert marks_cutoff_receipt(event_ts_ms=10, cutoff_ts_ms=10)["status"] == "PROVEN"
    assert marks_cutoff_receipt(event_ts_ms=11, cutoff_ts_ms=10)["status"] == "REJECTED"


def test_hvr_0687_age():
    assert marks_age_receipt(event_ts_ms=10, oldest_allowed_ts_ms=10)["status"] == "PROVEN"
    assert marks_age_receipt(event_ts_ms=9, oldest_allowed_ts_ms=10)["status"] == "REJECTED"


def test_hvr_0688_duplicate_events():
    assert marks_duplicate_receipt(event_ids=["a", "b"])["status"] == "PROVEN"
    assert marks_duplicate_receipt(event_ids=["a", "a"])["status"] == "REJECTED"


def test_hvr_0689_bounded_retry_requires_checkpoint():
    assert marks_retry_receipt(attempts=2, max_attempts=3, checkpoint_saved=True)["status"] == "PROVEN"
    assert marks_retry_receipt(attempts=4, max_attempts=3, checkpoint_saved=True)["status"] == "REJECTED"


def test_hvr_0690_replay_is_deterministic():
    assert marks_replay_receipt(outputs=[{"equity": 1000}, {"equity": 1000}])["status"] == "PROVEN"
    assert marks_replay_receipt(outputs=[{"equity": 1000}, {"equity": 999}])["status"] == "REJECTED"


def test_hvr_0691_fills_are_unique():
    assert marks_fill_duplicate_receipt(fill_ids=["fill-a", "fill-b"])["status"] == "PROVEN"
    assert marks_fill_duplicate_receipt(fill_ids=["fill-a", "fill-a"])["status"] == "REJECTED"


def test_hvr_0692_rejected_fill_does_not_debit_funds():
    assert marks_rejection_no_debit_receipt(rejected=True, debited=False)["status"] == "PROVEN"
    assert marks_rejection_no_debit_receipt(rejected=True, debited=True)["status"] == "REJECTED"


def test_hvr_0693_partial_close_has_explicit_cost():
    assert marks_partial_close_receipt(close_quantity=1.0, open_quantity=2.0, fee_known=True, fee_amount=0.0)["status"] == "PROVEN"
    assert marks_partial_close_receipt(close_quantity=1.0, open_quantity=2.0, fee_known=False, fee_amount=0.0)["status"] == "REJECTED"


def test_hvr_0694_total_close_releases_margin():
    assert marks_total_close_release_receipt(close_quantity=2.0, open_quantity=2.0, released_margin=10.0)["status"] == "PROVEN"
    assert marks_total_close_release_receipt(close_quantity=2.0, open_quantity=2.0, released_margin=-1.0)["status"] == "REJECTED"


def test_hvr_0695_mark_must_be_liquidable():
    assert marks_mark_liquidability_receipt(mark_price=100.0, bid=99.0, ask=101.0)["status"] == "PROVEN"
    assert marks_mark_liquidability_receipt(mark_price=None, bid=99.0, ask=101.0)["status"] == "REJECTED"


def test_hvr_0696_balance_cannot_be_negative():
    assert marks_balance_receipt(balance=0.0)["status"] == "PROVEN"
    assert marks_balance_receipt(balance=-0.1)["status"] == "REJECTED"


def test_hvr_0697_funding_sign_is_explicit():
    assert marks_funding_sign_receipt(amount=1.0, direction="CREDIT")["status"] == "PROVEN"
    assert marks_funding_sign_receipt(amount=1.0, direction="DEBIT")["status"] == "REJECTED"


def test_hvr_0698_conversion_requires_rate():
    assert marks_conversion_receipt(fee_amount=1.0, fee_token="USDC", pnl_currency="USD", token_to_pnl_rate=1.0)["status"] == "PROVEN"
    assert marks_conversion_receipt(fee_amount=1.0, fee_token="USDC", pnl_currency="USD", token_to_pnl_rate=None)["status"] == "REJECTED"


def test_hvr_0699_crash_before_commit_is_recoverable():
    assert marks_commit_receipt(crashed=True, committed=False, checkpoint_saved=True)["status"] == "PROVEN"
    assert marks_commit_receipt(crashed=True, committed=True, checkpoint_saved=False)["status"] == "REJECTED"


def test_hvr_0700_concurrent_writes_are_unique():
    assert marks_concurrent_write_receipt(write_ids=["w1", "w2"])["status"] == "PROVEN"
    assert marks_concurrent_write_receipt(write_ids=["w1", "w1"])["status"] == "REJECTED"


def test_hvr_0701_marks_done_requires_all_proven_gates():
    checks = [
        marks_required_field_receipt({"coin": "BTC"}, field="coin"),
        marks_replay_receipt(outputs=[{"equity": 1000.0}, {"equity": 1000.0}]),
        marks_commit_receipt(crashed=False, committed=True, checkpoint_saved=False),
    ]
    assert marks_done_receipt(checks=checks)["status"] == "PROVEN"
    assert marks_done_receipt(checks=checks[:-1] + [{"status": "PROVEN"}])["status"] == "REJECTED"
