from src.hl_observer.venues.gate import (
    capacites,
    gate_age_receipt,
    gate_consumption_receipt,
    gate_crossed_book_receipt,
    gate_cutoff_receipt,
    gate_delta_receipt,
    gate_depth_receipt,
    gate_duplicate_receipt,
    gate_fee_order_receipt,
    gate_finite_receipt,
    gate_field_type_receipt,
    gate_maker_touch_receipt,
    gate_negative_size_receipt,
    gate_null_field_receipt,
    gate_quantity_receipt,
    gate_replay_receipt,
    gate_required_field_receipt,
    gate_retry_receipt,
    gate_safety_receipt,
    gate_staleness_receipt,
    gate_tick_receipt,
)


def test_hvr_0521_gate_baseline_is_safe():
    assert gate_safety_receipt(capacites())["status"] == "PROVEN"


def test_hvr_0522_required_field():
    assert gate_required_field_receipt({"coin": "BTC"}, field="coin")["status"] == "PROVEN"
    assert gate_required_field_receipt({}, field="coin")["status"] == "REJECTED"


def test_hvr_0523_null_field():
    assert gate_null_field_receipt({"coin": "BTC"}, field="coin")["status"] == "PROVEN"
    assert gate_null_field_receipt({"coin": None}, field="coin")["status"] == "REJECTED"


def test_hvr_0524_field_type():
    assert gate_field_type_receipt({"depth": 1.0}, field="depth", expected_type=float)["status"] == "PROVEN"
    assert gate_field_type_receipt({"depth": "1"}, field="depth", expected_type=float)["status"] == "REJECTED"


def test_hvr_0525_finite_value():
    assert gate_finite_receipt(1.5)["status"] == "PROVEN"
    assert gate_finite_receipt(float("nan"))["status"] == "REJECTED"


def test_hvr_0526_cutoff():
    assert gate_cutoff_receipt(event_ts_ms=10, cutoff_ts_ms=10)["status"] == "PROVEN"
    assert gate_cutoff_receipt(event_ts_ms=11, cutoff_ts_ms=10)["status"] == "REJECTED"


def test_hvr_0527_age():
    assert gate_age_receipt(event_ts_ms=10, oldest_allowed_ts_ms=10)["status"] == "PROVEN"
    assert gate_age_receipt(event_ts_ms=9, oldest_allowed_ts_ms=10)["status"] == "REJECTED"


def test_hvr_0528_duplicate_events():
    assert gate_duplicate_receipt(event_ids=["a", "b"])["status"] == "PROVEN"
    assert gate_duplicate_receipt(event_ids=["a", "a"])["status"] == "REJECTED"


def test_hvr_0529_bounded_retry_requires_checkpoint():
    assert gate_retry_receipt(attempts=2, max_attempts=3, checkpoint_saved=True)["status"] == "PROVEN"
    assert gate_retry_receipt(attempts=4, max_attempts=3, checkpoint_saved=True)["status"] == "REJECTED"


def test_hvr_0530_replay_is_deterministic():
    assert gate_replay_receipt(outputs=[{"bid": 100}, {"bid": 100}])["status"] == "PROVEN"
    assert gate_replay_receipt(outputs=[{"bid": 100}, {"bid": 101}])["status"] == "REJECTED"


def test_hvr_0531_full_depth_is_not_bbo():
    assert gate_depth_receipt(bids=[(100.0, 1.0)], asks=[(101.0, 1.0)], is_bbo=False)["status"] == "PROVEN"
    assert gate_depth_receipt(bids=[(100.0, 1.0)], asks=[(101.0, 1.0)], is_bbo=True)["status"] == "REJECTED"


def test_hvr_0532_book_must_not_be_crossed():
    assert gate_crossed_book_receipt(best_bid=100.0, best_ask=101.0)["status"] == "PROVEN"
    assert gate_crossed_book_receipt(best_bid=101.0, best_ask=100.0)["status"] == "REJECTED"


def test_hvr_0533_sizes_must_be_positive():
    assert gate_negative_size_receipt(sizes=[1.0, 2.0])["status"] == "PROVEN"
    assert gate_negative_size_receipt(sizes=[1.0, -1.0])["status"] == "REJECTED"


def test_hvr_0534_prices_must_match_tick():
    assert gate_tick_receipt(prices=[100.0, 100.5], tick_size=0.5)["status"] == "PROVEN"
    assert gate_tick_receipt(prices=[100.1], tick_size=0.5)["status"] == "REJECTED"


def test_hvr_0535_delta_requires_snapshot():
    assert gate_delta_receipt(has_snapshot=True, delta_count=1)["status"] == "PROVEN"
    assert gate_delta_receipt(has_snapshot=False, delta_count=1)["status"] == "REJECTED"


def test_hvr_0536_stale_l2_is_rejected():
    assert gate_staleness_receipt(now_ms=1000, received_ts_ms=900, max_age_ms=100)["status"] == "PROVEN"
    assert gate_staleness_receipt(now_ms=1001, received_ts_ms=900, max_age_ms=100)["status"] == "REJECTED"


def test_hvr_0537_quantity_must_fit_depth():
    assert gate_quantity_receipt(requested_quantity=1.0, visible_depth=2.0)["status"] == "PROVEN"
    assert gate_quantity_receipt(requested_quantity=3.0, visible_depth=2.0)["status"] == "REJECTED"


def test_hvr_0538_consumption_is_once_only():
    assert gate_consumption_receipt(consumed_quantity=1.0, available_quantity=2.0, already_consumed=1.0)["status"] == "PROVEN"
    assert gate_consumption_receipt(consumed_quantity=2.0, available_quantity=2.0, already_consumed=1.0)["status"] == "REJECTED"


def test_hvr_0539_touch_only_is_not_maker_fill():
    assert gate_maker_touch_receipt(touched=True, executed=True)["status"] == "PROVEN"
    assert gate_maker_touch_receipt(touched=True, executed=False)["status"] == "REJECTED"


def test_hvr_0540_maker_fee_must_not_exceed_taker_fee():
    assert gate_fee_order_receipt(maker_fee_bps=1.0, taker_fee_bps=2.0)["status"] == "PROVEN"
    assert gate_fee_order_receipt(maker_fee_bps=3.0, taker_fee_bps=2.0)["status"] == "REJECTED"
