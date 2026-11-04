from hl_observer.backtest.no_lookahead_guard import (
    assert_no_lookahead,
    find_lookahead_violations,
    lookahead_age_receipt,
    lookahead_balance_receipt,
    lookahead_commit_receipt,
    lookahead_concurrent_write_receipt,
    lookahead_conversion_receipt,
    lookahead_cutoff_receipt,
    lookahead_done_receipt,
    lookahead_duplicate_receipt,
    lookahead_field_type_receipt,
    lookahead_fill_duplicate_receipt,
    lookahead_finite_receipt,
    lookahead_funding_sign_receipt,
    lookahead_mark_liquidability_receipt,
    lookahead_null_field_receipt,
    lookahead_partial_close_receipt,
    lookahead_rejection_no_debit_receipt,
    lookahead_replay_receipt,
    lookahead_required_field_receipt,
    lookahead_retry_receipt,
    lookahead_safety_receipt,
    lookahead_total_close_release_receipt,
)


def _clean_events():
    return [{"decision_ts_ms": 100, "data_ts_ms": 100}, {"decision_ts_ms": 101, "data_ts_ms": 100}]


def test_hvr_0721_no_lookahead_baseline_is_safe():
    assert find_lookahead_violations(_clean_events()) == []
    assert_no_lookahead(_clean_events())
    assert lookahead_safety_receipt(find_lookahead_violations(_clean_events()))["status"] == "PROVEN"
    assert lookahead_safety_receipt([object()])["status"] == "REJECTED"


def test_hvr_0722_required_field():
    assert lookahead_required_field_receipt({"coin": "BTC"}, field="coin")["status"] == "PROVEN"
    assert lookahead_required_field_receipt({}, field="coin")["status"] == "REJECTED"


def test_hvr_0723_null_field():
    assert lookahead_null_field_receipt({"coin": "BTC"}, field="coin")["status"] == "PROVEN"
    assert lookahead_null_field_receipt({"coin": None}, field="coin")["status"] == "REJECTED"


def test_hvr_0724_field_type():
    assert lookahead_field_type_receipt({"depth": 1.0}, field="depth", expected_type=float)["status"] == "PROVEN"
    assert lookahead_field_type_receipt({"depth": "1"}, field="depth", expected_type=float)["status"] == "REJECTED"


def test_hvr_0725_finite_value():
    assert lookahead_finite_receipt(1.5)["status"] == "PROVEN"
    assert lookahead_finite_receipt(float("nan"))["status"] == "REJECTED"


def test_hvr_0726_cutoff():
    assert lookahead_cutoff_receipt(event_ts_ms=10, cutoff_ts_ms=10)["status"] == "PROVEN"
    assert lookahead_cutoff_receipt(event_ts_ms=11, cutoff_ts_ms=10)["status"] == "REJECTED"


def test_hvr_0727_age():
    assert lookahead_age_receipt(event_ts_ms=10, oldest_allowed_ts_ms=10)["status"] == "PROVEN"
    assert lookahead_age_receipt(event_ts_ms=9, oldest_allowed_ts_ms=10)["status"] == "REJECTED"


def test_hvr_0728_duplicate_events():
    assert lookahead_duplicate_receipt(event_ids=["a", "b"])["status"] == "PROVEN"
    assert lookahead_duplicate_receipt(event_ids=["a", "a"])["status"] == "REJECTED"


def test_hvr_0729_bounded_retry_requires_checkpoint():
    assert lookahead_retry_receipt(attempts=2, max_attempts=3, checkpoint_saved=True)["status"] == "PROVEN"
    assert lookahead_retry_receipt(attempts=4, max_attempts=3, checkpoint_saved=True)["status"] == "REJECTED"


def test_hvr_0730_replay_is_deterministic():
    assert lookahead_replay_receipt(outputs=[{"equity": 1000}, {"equity": 1000}])["status"] == "PROVEN"
    assert lookahead_replay_receipt(outputs=[{"equity": 1000}, {"equity": 999}])["status"] == "REJECTED"


def test_hvr_0731_future_l2_is_rejected():
    assert lookahead_cutoff_receipt(event_ts_ms=100, cutoff_ts_ms=100)["status"] == "PROVEN"
    assert lookahead_cutoff_receipt(event_ts_ms=101, cutoff_ts_ms=100)["status"] == "REJECTED"


def test_hvr_0732_timestamp_after_decision_is_rejected():
    assert find_lookahead_violations([{"decision_ts_ms": 100, "data_ts_ms": 101}])


def test_hvr_0733_causal_order_is_deterministic():
    assert lookahead_replay_receipt(outputs=[{"ts_ms": 100}, {"ts_ms": 100}])["status"] == "PROVEN"
    assert lookahead_replay_receipt(outputs=[{"ts_ms": 100}, {"ts_ms": 101}])["status"] == "REJECTED"


def test_hvr_0734_fill_requires_quantity():
    assert lookahead_required_field_receipt({"quantity": 1.0}, field="quantity")["status"] == "PROVEN"
    assert lookahead_required_field_receipt({}, field="quantity")["status"] == "REJECTED"


def test_hvr_0735_maker_queue_requires_finite_depth():
    assert lookahead_finite_receipt(1.0)["status"] == "PROVEN"
    assert lookahead_finite_receipt(float("inf"))["status"] == "REJECTED"


def test_hvr_0736_fills_are_unique():
    assert lookahead_fill_duplicate_receipt(fill_ids=["fill-a", "fill-b"])["status"] == "PROVEN"
    assert lookahead_fill_duplicate_receipt(fill_ids=["fill-a", "fill-a"])["status"] == "REJECTED"


def test_hvr_0737_partial_fill_is_not_full_without_explicit_quantity():
    assert lookahead_partial_close_receipt(close_quantity=1.0, open_quantity=2.0, fee_known=True, fee_amount=0.0)["status"] == "PROVEN"
    assert lookahead_partial_close_receipt(close_quantity=2.0, open_quantity=2.0, fee_known=True, fee_amount=0.0)["status"] == "REJECTED"


def test_hvr_0738_optimistic_latency_is_rejected():
    assert lookahead_cutoff_receipt(event_ts_ms=100, cutoff_ts_ms=100)["status"] == "PROVEN"
    assert lookahead_cutoff_receipt(event_ts_ms=101, cutoff_ts_ms=100)["status"] == "REJECTED"


def test_hvr_0739_impact_requires_non_negative_balance_and_liquid_mark():
    assert lookahead_balance_receipt(balance=0.0)["status"] == "PROVEN"
    assert lookahead_mark_liquidability_receipt(mark_price=100.0, bid=99.0, ask=101.0)["status"] == "PROVEN"
    assert lookahead_balance_receipt(balance=-0.1)["status"] == "REJECTED"


def test_hvr_0740_runtime_replay_commit_is_fail_closed():
    assert lookahead_commit_receipt(crashed=True, committed=False, checkpoint_saved=True)["status"] == "PROVEN"
    assert lookahead_concurrent_write_receipt(write_ids=["w1", "w2"])["status"] == "PROVEN"
    assert lookahead_concurrent_write_receipt(write_ids=["w1", "w1"])["status"] == "REJECTED"
    assert lookahead_total_close_release_receipt(close_quantity=2.0, open_quantity=2.0, released_margin=10.0)["status"] == "PROVEN"
    assert lookahead_funding_sign_receipt(amount=1.0, direction="CREDIT")["status"] == "PROVEN"
    assert lookahead_conversion_receipt(fee_amount=1.0, fee_token="USDC", pnl_currency="USD", token_to_pnl_rate=1.0)["status"] == "PROVEN"


def test_hvr_0741_lookahead_done_requires_all_proven_gates():
    checks = [
        lookahead_required_field_receipt({"coin": "BTC"}, field="coin"),
        lookahead_replay_receipt(outputs=[{"ts_ms": 100}, {"ts_ms": 100}]),
        lookahead_commit_receipt(crashed=False, committed=True, checkpoint_saved=False),
    ]
    assert lookahead_done_receipt(checks=checks)["status"] == "PROVEN"
    assert lookahead_done_receipt(checks=checks[:-1] + [{"status": "PROVEN"}])["status"] == "REJECTED"
