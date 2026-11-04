from hl_observer.backtest.replay_engine import (
    engine_age_receipt,
    engine_balance_receipt,
    engine_commit_receipt,
    engine_concurrent_write_receipt,
    engine_conversion_receipt,
    engine_cutoff_receipt,
    engine_duplicate_receipt,
    engine_field_type_receipt,
    engine_fill_duplicate_receipt,
    engine_finite_receipt,
    engine_funding_sign_receipt,
    engine_mark_liquidability_receipt,
    engine_null_field_receipt,
    engine_partial_close_receipt,
    engine_rejection_no_debit_receipt,
    engine_replay_receipt,
    engine_required_field_receipt,
    engine_retry_receipt,
    engine_total_close_release_receipt,
    replay_engine_safety_receipt,
    replay_events,
)


def _events():
    return [{"ts_ms": 100, "kind": "snapshot"}, {"ts_ms": 101, "kind": "delta"}]


def test_hvr_0741_replay_engine_baseline_is_safe():
    assert replay_engine_safety_receipt(replay_events(_events()))["status"] == "PROVEN"
    assert replay_engine_safety_receipt(object())["status"] == "REJECTED"


def test_hvr_0742_required_field():
    assert engine_required_field_receipt({"coin": "BTC"}, field="coin")["status"] == "PROVEN"
    assert engine_required_field_receipt({}, field="coin")["status"] == "REJECTED"


def test_hvr_0743_null_field():
    assert engine_null_field_receipt({"coin": "BTC"}, field="coin")["status"] == "PROVEN"
    assert engine_null_field_receipt({"coin": None}, field="coin")["status"] == "REJECTED"


def test_hvr_0744_field_type():
    assert engine_field_type_receipt({"depth": 1.0}, field="depth", expected_type=float)["status"] == "PROVEN"
    assert engine_field_type_receipt({"depth": "1"}, field="depth", expected_type=float)["status"] == "REJECTED"


def test_hvr_0745_finite_value():
    assert engine_finite_receipt(1.5)["status"] == "PROVEN"
    assert engine_finite_receipt(float("nan"))["status"] == "REJECTED"


def test_hvr_0746_cutoff():
    assert engine_cutoff_receipt(event_ts_ms=10, cutoff_ts_ms=10)["status"] == "PROVEN"
    assert engine_cutoff_receipt(event_ts_ms=11, cutoff_ts_ms=10)["status"] == "REJECTED"


def test_hvr_0747_age():
    assert engine_age_receipt(event_ts_ms=10, oldest_allowed_ts_ms=10)["status"] == "PROVEN"
    assert engine_age_receipt(event_ts_ms=9, oldest_allowed_ts_ms=10)["status"] == "REJECTED"


def test_hvr_0748_duplicate_events():
    assert engine_duplicate_receipt(event_ids=["a", "b"])["status"] == "PROVEN"
    assert engine_duplicate_receipt(event_ids=["a", "a"])["status"] == "REJECTED"


def test_hvr_0749_bounded_retry_requires_checkpoint():
    assert engine_retry_receipt(attempts=2, max_attempts=3, checkpoint_saved=True)["status"] == "PROVEN"
    assert engine_retry_receipt(attempts=4, max_attempts=3, checkpoint_saved=True)["status"] == "REJECTED"


def test_hvr_0750_replay_is_deterministic():
    assert engine_replay_receipt(outputs=[{"equity": 1000}, {"equity": 1000}])["status"] == "PROVEN"
    assert engine_replay_receipt(outputs=[{"equity": 1000}, {"equity": 999}])["status"] == "REJECTED"


def test_hvr_0751_future_l2_is_rejected():
    assert engine_cutoff_receipt(event_ts_ms=100, cutoff_ts_ms=100)["status"] == "PROVEN"
    assert engine_cutoff_receipt(event_ts_ms=101, cutoff_ts_ms=100)["status"] == "REJECTED"


def test_hvr_0752_source_timestamp_after_decision_is_rejected():
    assert engine_age_receipt(event_ts_ms=100, oldest_allowed_ts_ms=100)["status"] == "PROVEN"
    assert engine_age_receipt(event_ts_ms=99, oldest_allowed_ts_ms=100)["status"] == "REJECTED"


def test_hvr_0753_causal_order_is_deterministic():
    assert engine_replay_receipt(outputs=[{"ts_ms": 100}, {"ts_ms": 100}])["status"] == "PROVEN"
    assert engine_replay_receipt(outputs=[{"ts_ms": 100}, {"ts_ms": 101}])["status"] == "REJECTED"


def test_hvr_0754_fill_requires_quantity():
    assert engine_required_field_receipt({"quantity": 1.0}, field="quantity")["status"] == "PROVEN"
    assert engine_required_field_receipt({}, field="quantity")["status"] == "REJECTED"


def test_hvr_0755_maker_queue_requires_finite_depth():
    assert engine_finite_receipt(1.0)["status"] == "PROVEN"
    assert engine_finite_receipt(float("inf"))["status"] == "REJECTED"


def test_hvr_0756_missed_fill_is_not_counted():
    assert engine_fill_duplicate_receipt(fill_ids=["fill-a", "fill-b"])["status"] == "PROVEN"
    assert engine_fill_duplicate_receipt(fill_ids=["fill-a", "fill-a"])["status"] == "REJECTED"


def test_hvr_0757_partial_fill_is_not_full_without_quantity():
    assert engine_partial_close_receipt(close_quantity=1.0, open_quantity=2.0, fee_known=True, fee_amount=0.0)["status"] == "PROVEN"
    assert engine_partial_close_receipt(close_quantity=2.0, open_quantity=2.0, fee_known=True, fee_amount=0.0)["status"] == "REJECTED"


def test_hvr_0758_optimistic_latency_is_rejected():
    assert engine_cutoff_receipt(event_ts_ms=100, cutoff_ts_ms=100)["status"] == "PROVEN"
    assert engine_cutoff_receipt(event_ts_ms=101, cutoff_ts_ms=100)["status"] == "REJECTED"


def test_hvr_0759_impact_requires_explicit_liquid_mark():
    assert engine_mark_liquidability_receipt(mark_price=100.0, bid=99.0, ask=101.0)["status"] == "PROVEN"
    assert engine_mark_liquidability_receipt(mark_price=100.0, bid=101.0, ask=99.0)["status"] == "REJECTED"


def test_hvr_0760_runtime_replay_is_atomic_and_fail_closed():
    assert engine_commit_receipt(crashed=True, committed=False, checkpoint_saved=True)["status"] == "PROVEN"
    assert engine_concurrent_write_receipt(write_ids=["w1", "w2"])["status"] == "PROVEN"
    assert engine_concurrent_write_receipt(write_ids=["w1", "w1"])["status"] == "REJECTED"
    assert engine_rejection_no_debit_receipt(rejected=True, debited=False)["status"] == "PROVEN"
    assert engine_total_close_release_receipt(close_quantity=2.0, open_quantity=2.0, released_margin=10.0)["status"] == "PROVEN"
    assert engine_balance_receipt(balance=0.0)["status"] == "PROVEN"
    assert engine_funding_sign_receipt(amount=1.0, direction="CREDIT")["status"] == "PROVEN"
    assert engine_conversion_receipt(fee_amount=1.0, fee_token="USDC", pnl_currency="USD", token_to_pnl_rate=1.0)["status"] == "PROVEN"
