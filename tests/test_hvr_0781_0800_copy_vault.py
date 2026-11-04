from hl_observer.backtest.runtime_parity import (
    RuntimeReplayParityResult,
    parity_age_receipt,
    parity_balance_receipt,
    parity_commit_receipt,
    parity_concurrent_write_receipt,
    parity_conversion_receipt,
    parity_cutoff_receipt,
    parity_duplicate_receipt,
    parity_field_type_receipt,
    parity_fill_duplicate_receipt,
    parity_finite_receipt,
    parity_funding_sign_receipt,
    parity_mark_liquidability_receipt,
    parity_null_field_receipt,
    parity_partial_close_receipt,
    parity_rejection_no_debit_receipt,
    parity_replay_receipt,
    parity_required_field_receipt,
    parity_retry_receipt,
    parity_total_close_release_receipt,
    runtime_parity_safety_receipt,
)


def _result():
    return RuntimeReplayParityResult(None, None, None, None, True, True, False, ())


def test_hvr_0781_runtime_parity_baseline_is_safe():
    assert runtime_parity_safety_receipt(_result())["status"] == "PROVEN"
    assert runtime_parity_safety_receipt(RuntimeReplayParityResult(None, None, None, None, False, True, False, ("DIVERGED",)))["status"] == "REJECTED"


def test_hvr_0782_required_field():
    assert parity_required_field_receipt({"coin": "BTC"}, field="coin")["status"] == "PROVEN"
    assert parity_required_field_receipt({}, field="coin")["status"] == "REJECTED"


def test_hvr_0783_null_field():
    assert parity_null_field_receipt({"coin": "BTC"}, field="coin")["status"] == "PROVEN"
    assert parity_null_field_receipt({"coin": None}, field="coin")["status"] == "REJECTED"


def test_hvr_0784_field_type():
    assert parity_field_type_receipt({"depth": 1.0}, field="depth", expected_type=float)["status"] == "PROVEN"
    assert parity_field_type_receipt({"depth": "1"}, field="depth", expected_type=float)["status"] == "REJECTED"


def test_hvr_0785_finite_value():
    assert parity_finite_receipt(1.5)["status"] == "PROVEN"
    assert parity_finite_receipt(float("nan"))["status"] == "REJECTED"


def test_hvr_0786_cutoff():
    assert parity_cutoff_receipt(event_ts_ms=10, cutoff_ts_ms=10)["status"] == "PROVEN"
    assert parity_cutoff_receipt(event_ts_ms=11, cutoff_ts_ms=10)["status"] == "REJECTED"


def test_hvr_0787_age():
    assert parity_age_receipt(event_ts_ms=10, oldest_allowed_ts_ms=10)["status"] == "PROVEN"
    assert parity_age_receipt(event_ts_ms=9, oldest_allowed_ts_ms=10)["status"] == "REJECTED"


def test_hvr_0788_duplicate_events():
    assert parity_duplicate_receipt(event_ids=["a", "b"])["status"] == "PROVEN"
    assert parity_duplicate_receipt(event_ids=["a", "a"])["status"] == "REJECTED"


def test_hvr_0789_bounded_retry_requires_checkpoint():
    assert parity_retry_receipt(attempts=2, max_attempts=3, checkpoint_saved=True)["status"] == "PROVEN"
    assert parity_retry_receipt(attempts=4, max_attempts=3, checkpoint_saved=True)["status"] == "REJECTED"


def test_hvr_0790_replay_is_deterministic():
    assert parity_replay_receipt(outputs=[{"equity": 1000}, {"equity": 1000}])["status"] == "PROVEN"
    assert parity_replay_receipt(outputs=[{"equity": 1000}, {"equity": 999}])["status"] == "REJECTED"


def test_hvr_0791_future_l2_is_rejected():
    assert parity_cutoff_receipt(event_ts_ms=100, cutoff_ts_ms=100)["status"] == "PROVEN"
    assert parity_cutoff_receipt(event_ts_ms=101, cutoff_ts_ms=100)["status"] == "REJECTED"


def test_hvr_0792_source_timestamp_after_decision_is_rejected():
    assert parity_age_receipt(event_ts_ms=100, oldest_allowed_ts_ms=100)["status"] == "PROVEN"
    assert parity_age_receipt(event_ts_ms=99, oldest_allowed_ts_ms=100)["status"] == "REJECTED"


def test_hvr_0793_causal_order_is_deterministic():
    assert parity_replay_receipt(outputs=[{"ts_ms": 100}, {"ts_ms": 100}])["status"] == "PROVEN"
    assert parity_replay_receipt(outputs=[{"ts_ms": 100}, {"ts_ms": 101}])["status"] == "REJECTED"


def test_hvr_0794_fill_requires_quantity():
    assert parity_required_field_receipt({"quantity": 1.0}, field="quantity")["status"] == "PROVEN"
    assert parity_required_field_receipt({}, field="quantity")["status"] == "REJECTED"


def test_hvr_0795_maker_queue_requires_finite_depth():
    assert parity_finite_receipt(1.0)["status"] == "PROVEN"
    assert parity_finite_receipt(float("inf"))["status"] == "REJECTED"


def test_hvr_0796_fills_are_unique():
    assert parity_fill_duplicate_receipt(fill_ids=["fill-a", "fill-b"])["status"] == "PROVEN"
    assert parity_fill_duplicate_receipt(fill_ids=["fill-a", "fill-a"])["status"] == "REJECTED"


def test_hvr_0797_partial_fill_is_not_full_without_quantity():
    assert parity_partial_close_receipt(close_quantity=1.0, open_quantity=2.0, fee_known=True, fee_amount=0.0)["status"] == "PROVEN"
    assert parity_partial_close_receipt(close_quantity=2.0, open_quantity=2.0, fee_known=True, fee_amount=0.0)["status"] == "REJECTED"


def test_hvr_0798_optimistic_latency_is_rejected():
    assert parity_cutoff_receipt(event_ts_ms=100, cutoff_ts_ms=100)["status"] == "PROVEN"
    assert parity_cutoff_receipt(event_ts_ms=101, cutoff_ts_ms=100)["status"] == "REJECTED"


def test_hvr_0799_impact_requires_explicit_liquid_mark():
    assert parity_mark_liquidability_receipt(mark_price=100.0, bid=99.0, ask=101.0)["status"] == "PROVEN"
    assert parity_mark_liquidability_receipt(mark_price=100.0, bid=101.0, ask=99.0)["status"] == "REJECTED"


def test_hvr_0800_runtime_replay_is_atomic_and_fail_closed():
    assert parity_commit_receipt(crashed=True, committed=False, checkpoint_saved=True)["status"] == "PROVEN"
    assert parity_concurrent_write_receipt(write_ids=["w1", "w2"])["status"] == "PROVEN"
    assert parity_concurrent_write_receipt(write_ids=["w1", "w1"])["status"] == "REJECTED"
    assert parity_rejection_no_debit_receipt(rejected=True, debited=False)["status"] == "PROVEN"
    assert parity_total_close_release_receipt(close_quantity=2.0, open_quantity=2.0, released_margin=10.0)["status"] == "PROVEN"
    assert parity_balance_receipt(balance=0.0)["status"] == "PROVEN"
    assert parity_funding_sign_receipt(amount=1.0, direction="CREDIT")["status"] == "PROVEN"
    assert parity_conversion_receipt(fee_amount=1.0, fee_token="USDC", pnl_currency="USD", token_to_pnl_rate=1.0)["status"] == "PROVEN"
