from hl_observer.market_data.live_l2_service import (
    l2_age_receipt,
    l2_consumption_receipt,
    l2_crossed_book_receipt,
    l2_cutoff_receipt,
    l2_delta_receipt,
    l2_depth_receipt,
    l2_duplicate_receipt,
    l2_fee_order_receipt,
    l2_finite_receipt,
    l2_field_type_receipt,
    l2_maker_touch_receipt,
    l2_negative_size_receipt,
    l2_null_field_receipt,
    l2_quantity_receipt,
    l2_replay_receipt,
    l2_required_field_receipt,
    l2_retry_receipt,
    l2_safety_receipt,
    l2_staleness_receipt,
    l2_tick_receipt,
)


def _payload() -> dict[str, object]:
    return {
        "bids": [[100.0, 2.0], [99.0, 2.0]],
        "asks": [[101.0, 2.0], [102.0, 2.0]],
        "received_ts_ms": 900,
        "depth_usd": 200.0,
        "data_origin": "REAL",
        "source": "hyperliquid:ws:l2Book",
    }


def test_hvr_0501_l2_baseline_is_safe():
    assert l2_safety_receipt(_payload(), coin="BTC", now_ms=1000)["status"] == "PROVEN"


def test_hvr_0502_required_field():
    assert l2_required_field_receipt({"coin": "BTC"}, field="coin")["status"] == "PROVEN"
    assert l2_required_field_receipt({}, field="coin")["status"] == "REJECTED"


def test_hvr_0503_null_field():
    assert l2_null_field_receipt({"coin": "BTC"}, field="coin")["status"] == "PROVEN"
    assert l2_null_field_receipt({"coin": None}, field="coin")["status"] == "REJECTED"


def test_hvr_0504_field_type():
    assert l2_field_type_receipt({"depth": 1.0}, field="depth", expected_type=float)["status"] == "PROVEN"
    assert l2_field_type_receipt({"depth": "1"}, field="depth", expected_type=float)["status"] == "REJECTED"


def test_hvr_0505_finite_value():
    assert l2_finite_receipt(1.5)["status"] == "PROVEN"
    assert l2_finite_receipt(float("nan"))["status"] == "REJECTED"


def test_hvr_0506_cutoff():
    assert l2_cutoff_receipt(event_ts_ms=10, cutoff_ts_ms=10)["status"] == "PROVEN"
    assert l2_cutoff_receipt(event_ts_ms=11, cutoff_ts_ms=10)["status"] == "REJECTED"


def test_hvr_0507_age():
    assert l2_age_receipt(event_ts_ms=10, oldest_allowed_ts_ms=10)["status"] == "PROVEN"
    assert l2_age_receipt(event_ts_ms=9, oldest_allowed_ts_ms=10)["status"] == "REJECTED"


def test_hvr_0508_duplicate_events():
    assert l2_duplicate_receipt(event_ids=["a", "b"])["status"] == "PROVEN"
    assert l2_duplicate_receipt(event_ids=["a", "a"])["status"] == "REJECTED"


def test_hvr_0509_bounded_retry_requires_checkpoint():
    assert l2_retry_receipt(attempts=2, max_attempts=3, checkpoint_saved=True)["status"] == "PROVEN"
    assert l2_retry_receipt(attempts=4, max_attempts=3, checkpoint_saved=True)["status"] == "REJECTED"


def test_hvr_0510_replay_is_deterministic():
    assert l2_replay_receipt(outputs=[{"bid": 100}, {"bid": 100}])["status"] == "PROVEN"
    assert l2_replay_receipt(outputs=[{"bid": 100}, {"bid": 101}])["status"] == "REJECTED"


def test_hvr_0511_full_depth_is_not_bbo():
    assert l2_depth_receipt(bids=[(100.0, 1.0)], asks=[(101.0, 1.0)], is_bbo=False)["status"] == "PROVEN"
    assert l2_depth_receipt(bids=[(100.0, 1.0)], asks=[(101.0, 1.0)], is_bbo=True)["status"] == "REJECTED"


def test_hvr_0512_book_must_not_be_crossed():
    assert l2_crossed_book_receipt(best_bid=100.0, best_ask=101.0)["status"] == "PROVEN"
    assert l2_crossed_book_receipt(best_bid=101.0, best_ask=100.0)["status"] == "REJECTED"


def test_hvr_0513_sizes_must_be_positive():
    assert l2_negative_size_receipt(sizes=[1.0, 2.0])["status"] == "PROVEN"
    assert l2_negative_size_receipt(sizes=[1.0, -1.0])["status"] == "REJECTED"


def test_hvr_0514_prices_must_match_tick():
    assert l2_tick_receipt(prices=[100.0, 100.5], tick_size=0.5)["status"] == "PROVEN"
    assert l2_tick_receipt(prices=[100.1], tick_size=0.5)["status"] == "REJECTED"


def test_hvr_0515_delta_requires_snapshot():
    assert l2_delta_receipt(has_snapshot=True, delta_count=1)["status"] == "PROVEN"
    assert l2_delta_receipt(has_snapshot=False, delta_count=1)["status"] == "REJECTED"


def test_hvr_0516_l2_stale_is_rejected():
    assert l2_staleness_receipt(now_ms=1000, received_ts_ms=900, max_age_ms=100)["status"] == "PROVEN"
    assert l2_staleness_receipt(now_ms=1001, received_ts_ms=900, max_age_ms=100)["status"] == "REJECTED"


def test_hvr_0517_quantity_must_fit_depth():
    assert l2_quantity_receipt(requested_quantity=1.0, visible_depth=2.0)["status"] == "PROVEN"
    assert l2_quantity_receipt(requested_quantity=3.0, visible_depth=2.0)["status"] == "REJECTED"


def test_hvr_0518_consumption_is_once_only():
    assert l2_consumption_receipt(consumed_quantity=1.0, available_quantity=2.0, already_consumed=1.0)["status"] == "PROVEN"
    assert l2_consumption_receipt(consumed_quantity=2.0, available_quantity=2.0, already_consumed=1.0)["status"] == "REJECTED"


def test_hvr_0519_touch_only_is_not_maker_fill():
    assert l2_maker_touch_receipt(touched=True, executed=True)["status"] == "PROVEN"
    assert l2_maker_touch_receipt(touched=True, executed=False)["status"] == "REJECTED"


def test_hvr_0520_maker_fee_must_not_exceed_taker_fee():
    assert l2_fee_order_receipt(maker_fee_bps=1.0, taker_fee_bps=2.0)["status"] == "PROVEN"
    assert l2_fee_order_receipt(maker_fee_bps=3.0, taker_fee_bps=2.0)["status"] == "REJECTED"
