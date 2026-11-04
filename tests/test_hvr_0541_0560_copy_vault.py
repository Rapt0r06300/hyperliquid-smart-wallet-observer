from hl_observer.paper_trading.execution_truth import (
    ExecutionTruth,
    execution_truth_safety_receipt,
    truth_age_receipt,
    truth_consumption_receipt,
    truth_crossed_book_receipt,
    truth_cutoff_receipt,
    truth_delta_receipt,
    truth_depth_receipt,
    truth_duplicate_receipt,
    truth_done_receipt,
    truth_fee_order_receipt,
    truth_finite_receipt,
    truth_field_type_receipt,
    truth_maker_touch_receipt,
    truth_negative_size_receipt,
    truth_null_field_receipt,
    truth_quantity_receipt,
    truth_replay_receipt,
    truth_required_field_receipt,
    truth_retry_receipt,
    truth_staleness_receipt,
    truth_tick_receipt,
)


def _truth() -> ExecutionTruth:
    return ExecutionTruth.from_levels(
        coin="BTC",
        bids=[(100.0, 2.0), (99.0, 2.0)],
        asks=[(101.0, 2.0), (102.0, 2.0)],
        received_ts_ms=900,
        exchange_ts_ms=800,
        source="hyperliquid:ws:l2Book",
        data_origin="REAL",
    )


def test_hvr_0541_execution_truth_baseline_is_safe():
    assert execution_truth_safety_receipt(_truth())["status"] == "PROVEN"
    assert execution_truth_safety_receipt(object())["status"] == "REJECTED"


def test_hvr_0542_required_field():
    assert truth_required_field_receipt({"coin": "BTC"}, field="coin")["status"] == "PROVEN"
    assert truth_required_field_receipt({}, field="coin")["status"] == "REJECTED"


def test_hvr_0543_null_field():
    assert truth_null_field_receipt({"coin": "BTC"}, field="coin")["status"] == "PROVEN"
    assert truth_null_field_receipt({"coin": None}, field="coin")["status"] == "REJECTED"


def test_hvr_0544_field_type():
    assert truth_field_type_receipt({"depth": 1.0}, field="depth", expected_type=float)["status"] == "PROVEN"
    assert truth_field_type_receipt({"depth": "1"}, field="depth", expected_type=float)["status"] == "REJECTED"


def test_hvr_0545_finite_value():
    assert truth_finite_receipt(1.5)["status"] == "PROVEN"
    assert truth_finite_receipt(float("nan"))["status"] == "REJECTED"


def test_hvr_0546_cutoff():
    assert truth_cutoff_receipt(event_ts_ms=10, cutoff_ts_ms=10)["status"] == "PROVEN"
    assert truth_cutoff_receipt(event_ts_ms=11, cutoff_ts_ms=10)["status"] == "REJECTED"


def test_hvr_0547_age():
    assert truth_age_receipt(event_ts_ms=10, oldest_allowed_ts_ms=10)["status"] == "PROVEN"
    assert truth_age_receipt(event_ts_ms=9, oldest_allowed_ts_ms=10)["status"] == "REJECTED"


def test_hvr_0548_duplicate_events():
    assert truth_duplicate_receipt(event_ids=["a", "b"])["status"] == "PROVEN"
    assert truth_duplicate_receipt(event_ids=["a", "a"])["status"] == "REJECTED"


def test_hvr_0549_bounded_retry_requires_checkpoint():
    assert truth_retry_receipt(attempts=2, max_attempts=3, checkpoint_saved=True)["status"] == "PROVEN"
    assert truth_retry_receipt(attempts=4, max_attempts=3, checkpoint_saved=True)["status"] == "REJECTED"


def test_hvr_0550_replay_is_deterministic():
    assert truth_replay_receipt(outputs=[{"bid": 100}, {"bid": 100}])["status"] == "PROVEN"
    assert truth_replay_receipt(outputs=[{"bid": 100}, {"bid": 101}])["status"] == "REJECTED"


def test_hvr_0551_full_depth_is_not_bbo():
    assert truth_depth_receipt(bids=[(100.0, 1.0)], asks=[(101.0, 1.0)], is_bbo=False)["status"] == "PROVEN"
    assert truth_depth_receipt(bids=[(100.0, 1.0)], asks=[(101.0, 1.0)], is_bbo=True)["status"] == "REJECTED"


def test_hvr_0552_book_must_not_be_crossed():
    assert truth_crossed_book_receipt(best_bid=100.0, best_ask=101.0)["status"] == "PROVEN"
    assert truth_crossed_book_receipt(best_bid=101.0, best_ask=100.0)["status"] == "REJECTED"


def test_hvr_0553_sizes_must_be_positive():
    assert truth_negative_size_receipt(sizes=[1.0, 2.0])["status"] == "PROVEN"
    assert truth_negative_size_receipt(sizes=[1.0, -1.0])["status"] == "REJECTED"


def test_hvr_0554_prices_must_match_tick():
    assert truth_tick_receipt(prices=[100.0, 100.5], tick_size=0.5)["status"] == "PROVEN"
    assert truth_tick_receipt(prices=[100.1], tick_size=0.5)["status"] == "REJECTED"


def test_hvr_0555_delta_requires_snapshot():
    assert truth_delta_receipt(has_snapshot=True, delta_count=1)["status"] == "PROVEN"
    assert truth_delta_receipt(has_snapshot=False, delta_count=1)["status"] == "REJECTED"


def test_hvr_0556_stale_l2_is_rejected():
    assert truth_staleness_receipt(now_ms=1000, received_ts_ms=900, max_age_ms=100)["status"] == "PROVEN"
    assert truth_staleness_receipt(now_ms=1001, received_ts_ms=900, max_age_ms=100)["status"] == "REJECTED"


def test_hvr_0557_quantity_must_fit_depth():
    assert truth_quantity_receipt(requested_quantity=1.0, visible_depth=2.0)["status"] == "PROVEN"
    assert truth_quantity_receipt(requested_quantity=3.0, visible_depth=2.0)["status"] == "REJECTED"


def test_hvr_0558_consumption_is_once_only():
    assert truth_consumption_receipt(consumed_quantity=1.0, available_quantity=2.0, already_consumed=1.0)["status"] == "PROVEN"
    assert truth_consumption_receipt(consumed_quantity=2.0, available_quantity=2.0, already_consumed=1.0)["status"] == "REJECTED"


def test_hvr_0559_touch_only_is_not_maker_fill():
    assert truth_maker_touch_receipt(touched=True, executed=True)["status"] == "PROVEN"
    assert truth_maker_touch_receipt(touched=True, executed=False)["status"] == "REJECTED"


def test_hvr_0560_maker_fee_must_not_exceed_taker_fee():
    assert truth_fee_order_receipt(maker_fee_bps=1.0, taker_fee_bps=2.0)["status"] == "PROVEN"
    assert truth_fee_order_receipt(maker_fee_bps=3.0, taker_fee_bps=2.0)["status"] == "REJECTED"


def test_hvr_0561_truth_done_requires_all_proven_gates():
    checks = [
        truth_required_field_receipt({"coin": "BTC"}, field="coin"),
        truth_replay_receipt(outputs=[{"mark": 100}, {"mark": 100}]),
        truth_fee_order_receipt(maker_fee_bps=1.0, taker_fee_bps=2.0),
    ]
    assert truth_done_receipt(checks=checks)["status"] == "PROVEN"
    assert truth_done_receipt(checks=checks[:-1] + [{"status": "PROVEN"}])["status"] == "REJECTED"
