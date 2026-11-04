from hl_observer.backtest.execution_realism import (
    adverse_selection_penalty_bps,
    execution_realism_safety_receipt,
    execution_age_receipt,
    execution_balance_receipt,
    execution_commit_receipt,
    execution_concurrent_write_receipt,
    execution_conversion_receipt,
    execution_cutoff_receipt,
    execution_duplicate_receipt,
    execution_field_type_receipt,
    execution_fill_duplicate_receipt,
    execution_finite_receipt,
    execution_funding_sign_receipt,
    execution_mark_liquidability_receipt,
    execution_null_field_receipt,
    execution_partial_close_receipt,
    execution_rejection_no_debit_receipt,
    execution_replay_receipt,
    execution_required_field_receipt,
    execution_retry_receipt,
    execution_total_close_release_receipt,
    latency_jitter_ms,
    maker_fill_probability,
)


def _report():
    return {
        "fill_probability": maker_fill_probability(queue_ahead_notional=1.0, incoming_flow_notional=2.0),
        "penalty_bps": adverse_selection_penalty_bps(4.0),
        "latency_ms": latency_jitter_ms(10.0),
    }


def test_hvr_0761_execution_realism_baseline_is_safe():
    assert execution_realism_safety_receipt(_report())["status"] == "PROVEN"
    assert execution_realism_safety_receipt(object())["status"] == "REJECTED"


def test_hvr_0762_required_field():
    assert execution_required_field_receipt({"coin": "BTC"}, field="coin")["status"] == "PROVEN"
    assert execution_required_field_receipt({}, field="coin")["status"] == "REJECTED"


def test_hvr_0763_null_field():
    assert execution_null_field_receipt({"coin": "BTC"}, field="coin")["status"] == "PROVEN"
    assert execution_null_field_receipt({"coin": None}, field="coin")["status"] == "REJECTED"


def test_hvr_0764_field_type():
    assert execution_field_type_receipt({"depth": 1.0}, field="depth", expected_type=float)["status"] == "PROVEN"
    assert execution_field_type_receipt({"depth": "1"}, field="depth", expected_type=float)["status"] == "REJECTED"


def test_hvr_0765_finite_value():
    assert execution_finite_receipt(1.5)["status"] == "PROVEN"
    assert execution_finite_receipt(float("nan"))["status"] == "REJECTED"


def test_hvr_0766_cutoff():
    assert execution_cutoff_receipt(event_ts_ms=10, cutoff_ts_ms=10)["status"] == "PROVEN"
    assert execution_cutoff_receipt(event_ts_ms=11, cutoff_ts_ms=10)["status"] == "REJECTED"


def test_hvr_0767_age():
    assert execution_age_receipt(event_ts_ms=10, oldest_allowed_ts_ms=10)["status"] == "PROVEN"
    assert execution_age_receipt(event_ts_ms=9, oldest_allowed_ts_ms=10)["status"] == "REJECTED"


def test_hvr_0768_duplicate_events():
    assert execution_duplicate_receipt(event_ids=["a", "b"])["status"] == "PROVEN"
    assert execution_duplicate_receipt(event_ids=["a", "a"])["status"] == "REJECTED"


def test_hvr_0769_bounded_retry_requires_checkpoint():
    assert execution_retry_receipt(attempts=2, max_attempts=3, checkpoint_saved=True)["status"] == "PROVEN"
    assert execution_retry_receipt(attempts=4, max_attempts=3, checkpoint_saved=True)["status"] == "REJECTED"


def test_hvr_0770_replay_is_deterministic():
    assert execution_replay_receipt(outputs=[{"equity": 1000}, {"equity": 1000}])["status"] == "PROVEN"
    assert execution_replay_receipt(outputs=[{"equity": 1000}, {"equity": 999}])["status"] == "REJECTED"


def test_hvr_0771_future_l2_is_rejected():
    assert execution_cutoff_receipt(event_ts_ms=100, cutoff_ts_ms=100)["status"] == "PROVEN"
    assert execution_cutoff_receipt(event_ts_ms=101, cutoff_ts_ms=100)["status"] == "REJECTED"


def test_hvr_0772_source_timestamp_after_decision_is_rejected():
    assert execution_age_receipt(event_ts_ms=100, oldest_allowed_ts_ms=100)["status"] == "PROVEN"
    assert execution_age_receipt(event_ts_ms=99, oldest_allowed_ts_ms=100)["status"] == "REJECTED"


def test_hvr_0773_causal_order_is_deterministic():
    assert execution_replay_receipt(outputs=[{"ts_ms": 100}, {"ts_ms": 100}])["status"] == "PROVEN"
    assert execution_replay_receipt(outputs=[{"ts_ms": 100}, {"ts_ms": 101}])["status"] == "REJECTED"


def test_hvr_0774_fill_requires_quantity():
    assert execution_required_field_receipt({"quantity": 1.0}, field="quantity")["status"] == "PROVEN"
    assert execution_required_field_receipt({}, field="quantity")["status"] == "REJECTED"


def test_hvr_0775_maker_queue_requires_finite_depth():
    assert execution_finite_receipt(1.0)["status"] == "PROVEN"
    assert execution_finite_receipt(float("inf"))["status"] == "REJECTED"


def test_hvr_0776_fills_are_unique():
    assert execution_fill_duplicate_receipt(fill_ids=["fill-a", "fill-b"])["status"] == "PROVEN"
    assert execution_fill_duplicate_receipt(fill_ids=["fill-a", "fill-a"])["status"] == "REJECTED"


def test_hvr_0777_partial_fill_is_not_full_without_quantity():
    assert execution_partial_close_receipt(close_quantity=1.0, open_quantity=2.0, fee_known=True, fee_amount=0.0)["status"] == "PROVEN"
    assert execution_partial_close_receipt(close_quantity=2.0, open_quantity=2.0, fee_known=True, fee_amount=0.0)["status"] == "REJECTED"


def test_hvr_0778_optimistic_latency_is_rejected():
    assert execution_cutoff_receipt(event_ts_ms=100, cutoff_ts_ms=100)["status"] == "PROVEN"
    assert execution_cutoff_receipt(event_ts_ms=101, cutoff_ts_ms=100)["status"] == "REJECTED"


def test_hvr_0779_impact_requires_explicit_liquid_mark():
    assert execution_mark_liquidability_receipt(mark_price=100.0, bid=99.0, ask=101.0)["status"] == "PROVEN"
    assert execution_mark_liquidability_receipt(mark_price=100.0, bid=101.0, ask=99.0)["status"] == "REJECTED"


def test_hvr_0780_runtime_replay_is_atomic_and_fail_closed():
    assert execution_commit_receipt(crashed=True, committed=False, checkpoint_saved=True)["status"] == "PROVEN"
    assert execution_concurrent_write_receipt(write_ids=["w1", "w2"])["status"] == "PROVEN"
    assert execution_concurrent_write_receipt(write_ids=["w1", "w1"])["status"] == "REJECTED"
    assert execution_rejection_no_debit_receipt(rejected=True, debited=False)["status"] == "PROVEN"
    assert execution_total_close_release_receipt(close_quantity=2.0, open_quantity=2.0, released_margin=10.0)["status"] == "PROVEN"
    assert execution_balance_receipt(balance=0.0)["status"] == "PROVEN"
    assert execution_funding_sign_receipt(amount=1.0, direction="CREDIT")["status"] == "PROVEN"
    assert execution_conversion_receipt(fee_amount=1.0, fee_token="USDC", pnl_currency="USD", token_to_pnl_rate=1.0)["status"] == "PROVEN"
