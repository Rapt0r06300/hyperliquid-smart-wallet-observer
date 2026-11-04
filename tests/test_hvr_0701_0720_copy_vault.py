from hl_observer.backtest.book_replay import (
    book_replay_safety_receipt,
    replay_age_receipt,
    replay_balance_receipt,
    replay_commit_receipt,
    replay_concurrent_write_receipt,
    replay_conversion_receipt,
    replay_cutoff_receipt,
    replay_duplicate_receipt,
    replay_field_type_receipt,
    replay_fill_duplicate_receipt,
    replay_finite_receipt,
    replay_funding_sign_receipt,
    replay_mark_liquidability_receipt,
    replay_null_field_receipt,
    replay_partial_close_receipt,
    replay_rejection_no_debit_receipt,
    replay_replay_receipt,
    replay_required_field_receipt,
    replay_retry_receipt,
    replay_total_close_release_receipt,
    replay_book,
)


def _replay():
    return replay_book([
        {"type": "snapshot", "ts_ms": 100, "bids": [[100.0, 1.0]], "asks": [[101.0, 1.0]]},
        {"type": "delta", "ts_ms": 101, "side": "bid", "price": 100.0, "size": 2.0},
    ])


def test_hvr_0701_book_replay_baseline_is_safe():
    assert book_replay_safety_receipt(_replay())["status"] == "PROVEN"
    assert book_replay_safety_receipt(object())["status"] == "REJECTED"


def test_hvr_0702_required_field():
    assert replay_required_field_receipt({"coin": "BTC"}, field="coin")["status"] == "PROVEN"
    assert replay_required_field_receipt({}, field="coin")["status"] == "REJECTED"


def test_hvr_0703_null_field():
    assert replay_null_field_receipt({"coin": "BTC"}, field="coin")["status"] == "PROVEN"
    assert replay_null_field_receipt({"coin": None}, field="coin")["status"] == "REJECTED"


def test_hvr_0704_field_type():
    assert replay_field_type_receipt({"depth": 1.0}, field="depth", expected_type=float)["status"] == "PROVEN"
    assert replay_field_type_receipt({"depth": "1"}, field="depth", expected_type=float)["status"] == "REJECTED"


def test_hvr_0705_finite_value():
    assert replay_finite_receipt(1.5)["status"] == "PROVEN"
    assert replay_finite_receipt(float("nan"))["status"] == "REJECTED"


def test_hvr_0706_cutoff():
    assert replay_cutoff_receipt(event_ts_ms=10, cutoff_ts_ms=10)["status"] == "PROVEN"
    assert replay_cutoff_receipt(event_ts_ms=11, cutoff_ts_ms=10)["status"] == "REJECTED"


def test_hvr_0707_age():
    assert replay_age_receipt(event_ts_ms=10, oldest_allowed_ts_ms=10)["status"] == "PROVEN"
    assert replay_age_receipt(event_ts_ms=9, oldest_allowed_ts_ms=10)["status"] == "REJECTED"


def test_hvr_0708_duplicate_events():
    assert replay_duplicate_receipt(event_ids=["a", "b"])["status"] == "PROVEN"
    assert replay_duplicate_receipt(event_ids=["a", "a"])["status"] == "REJECTED"


def test_hvr_0709_bounded_retry_requires_checkpoint():
    assert replay_retry_receipt(attempts=2, max_attempts=3, checkpoint_saved=True)["status"] == "PROVEN"
    assert replay_retry_receipt(attempts=4, max_attempts=3, checkpoint_saved=True)["status"] == "REJECTED"


def test_hvr_0710_replay_is_deterministic():
    assert replay_replay_receipt(outputs=[{"equity": 1000}, {"equity": 1000}])["status"] == "PROVEN"
    assert replay_replay_receipt(outputs=[{"equity": 1000}, {"equity": 999}])["status"] == "REJECTED"


def test_hvr_0711_future_l2_is_not_accepted_as_a_replay_receipt():
    assert replay_cutoff_receipt(event_ts_ms=100, cutoff_ts_ms=100)["status"] == "PROVEN"
    assert replay_cutoff_receipt(event_ts_ms=101, cutoff_ts_ms=100)["status"] == "REJECTED"


def test_hvr_0712_source_timestamp_is_causal():
    assert replay_age_receipt(event_ts_ms=100, oldest_allowed_ts_ms=100)["status"] == "PROVEN"
    assert replay_age_receipt(event_ts_ms=99, oldest_allowed_ts_ms=100)["status"] == "REJECTED"


def test_hvr_0713_causal_order_is_deterministic():
    assert replay_replay_receipt(outputs=[{"ts_ms": 100}, {"ts_ms": 100}])["status"] == "PROVEN"
    assert replay_replay_receipt(outputs=[{"ts_ms": 100}, {"ts_ms": 101}])["status"] == "REJECTED"


def test_hvr_0714_fill_requires_quantity():
    assert replay_required_field_receipt({"quantity": 1.0}, field="quantity")["status"] == "PROVEN"
    assert replay_required_field_receipt({}, field="quantity")["status"] == "REJECTED"


def test_hvr_0715_maker_queue_requires_finite_depth():
    assert replay_finite_receipt(1.0)["status"] == "PROVEN"
    assert replay_finite_receipt(float("inf"))["status"] == "REJECTED"


def test_hvr_0716_fills_are_unique():
    assert replay_fill_duplicate_receipt(fill_ids=["fill-a", "fill-b"])["status"] == "PROVEN"
    assert replay_fill_duplicate_receipt(fill_ids=["fill-a", "fill-a"])["status"] == "REJECTED"


def test_hvr_0717_rejected_fill_does_not_debit_funds():
    assert replay_rejection_no_debit_receipt(rejected=True, debited=False)["status"] == "PROVEN"
    assert replay_rejection_no_debit_receipt(rejected=True, debited=True)["status"] == "REJECTED"


def test_hvr_0718_partial_close_has_explicit_cost():
    assert replay_partial_close_receipt(close_quantity=1.0, open_quantity=2.0, fee_known=True, fee_amount=0.0)["status"] == "PROVEN"
    assert replay_partial_close_receipt(close_quantity=1.0, open_quantity=2.0, fee_known=False, fee_amount=0.0)["status"] == "REJECTED"


def test_hvr_0719_scope_and_order_are_explicit():
    assert replay_mark_liquidability_receipt(mark_price=100.0, bid=99.0, ask=101.0)["status"] == "PROVEN"
    assert replay_mark_liquidability_receipt(mark_price=100.0, bid=101.0, ask=99.0)["status"] == "REJECTED"


def test_hvr_0720_atomic_commit_and_write_guards():
    assert replay_commit_receipt(crashed=True, committed=False, checkpoint_saved=True)["status"] == "PROVEN"
    assert replay_concurrent_write_receipt(write_ids=["w1", "w2"])["status"] == "PROVEN"
    assert replay_concurrent_write_receipt(write_ids=["w1", "w1"])["status"] == "REJECTED"
    assert replay_total_close_release_receipt(close_quantity=2.0, open_quantity=2.0, released_margin=10.0)["status"] == "PROVEN"
    assert replay_balance_receipt(balance=0.0)["status"] == "PROVEN"
    assert replay_funding_sign_receipt(amount=1.0, direction="CREDIT")["status"] == "PROVEN"
    assert replay_conversion_receipt(fee_amount=1.0, fee_token="USDC", pnl_currency="USD", token_to_pnl_rate=1.0)["status"] == "PROVEN"
