from hl_observer.paper_trading.liquidity_consumption import (
    LiquidityConsumptionLedger,
    liquidity_age_receipt,
    liquidity_consumption_receipt,
    liquidity_consumption_safety_receipt,
    liquidity_crossed_book_receipt,
    liquidity_cutoff_receipt,
    liquidity_delta_receipt,
    liquidity_depth_receipt,
    liquidity_duplicate_receipt,
    liquidity_done_receipt,
    liquidity_fee_order_receipt,
    liquidity_finite_receipt,
    liquidity_field_type_receipt,
    liquidity_maker_touch_receipt,
    liquidity_negative_size_receipt,
    liquidity_null_field_receipt,
    liquidity_quantity_receipt,
    liquidity_replay_receipt,
    liquidity_required_field_receipt,
    liquidity_retry_receipt,
    liquidity_staleness_receipt,
    liquidity_tick_receipt,
)


def test_hvr_0581_liquidity_consumption_baseline_is_safe():
    assert liquidity_consumption_safety_receipt(LiquidityConsumptionLedger())["status"] == "PROVEN"
    assert liquidity_consumption_safety_receipt(object())["status"] == "REJECTED"


def test_hvr_0582_required_field():
    assert liquidity_required_field_receipt({"coin": "BTC"}, field="coin")["status"] == "PROVEN"
    assert liquidity_required_field_receipt({}, field="coin")["status"] == "REJECTED"


def test_hvr_0583_null_field():
    assert liquidity_null_field_receipt({"coin": "BTC"}, field="coin")["status"] == "PROVEN"
    assert liquidity_null_field_receipt({"coin": None}, field="coin")["status"] == "REJECTED"


def test_hvr_0584_field_type():
    assert liquidity_field_type_receipt({"depth": 1.0}, field="depth", expected_type=float)["status"] == "PROVEN"
    assert liquidity_field_type_receipt({"depth": "1"}, field="depth", expected_type=float)["status"] == "REJECTED"


def test_hvr_0585_finite_value():
    assert liquidity_finite_receipt(1.5)["status"] == "PROVEN"
    assert liquidity_finite_receipt(float("nan"))["status"] == "REJECTED"


def test_hvr_0586_cutoff():
    assert liquidity_cutoff_receipt(event_ts_ms=10, cutoff_ts_ms=10)["status"] == "PROVEN"
    assert liquidity_cutoff_receipt(event_ts_ms=11, cutoff_ts_ms=10)["status"] == "REJECTED"


def test_hvr_0587_age():
    assert liquidity_age_receipt(event_ts_ms=10, oldest_allowed_ts_ms=10)["status"] == "PROVEN"
    assert liquidity_age_receipt(event_ts_ms=9, oldest_allowed_ts_ms=10)["status"] == "REJECTED"


def test_hvr_0588_duplicate_events():
    assert liquidity_duplicate_receipt(event_ids=["a", "b"])["status"] == "PROVEN"
    assert liquidity_duplicate_receipt(event_ids=["a", "a"])["status"] == "REJECTED"


def test_hvr_0589_bounded_retry_requires_checkpoint():
    assert liquidity_retry_receipt(attempts=2, max_attempts=3, checkpoint_saved=True)["status"] == "PROVEN"
    assert liquidity_retry_receipt(attempts=4, max_attempts=3, checkpoint_saved=True)["status"] == "REJECTED"


def test_hvr_0590_replay_is_deterministic():
    assert liquidity_replay_receipt(outputs=[{"fill": 1}, {"fill": 1}])["status"] == "PROVEN"
    assert liquidity_replay_receipt(outputs=[{"fill": 1}, {"fill": 2}])["status"] == "REJECTED"


def test_hvr_0591_full_depth_is_not_bbo():
    assert liquidity_depth_receipt(bids=[(100.0, 1.0)], asks=[(101.0, 1.0)], is_bbo=False)["status"] == "PROVEN"
    assert liquidity_depth_receipt(bids=[(100.0, 1.0)], asks=[(101.0, 1.0)], is_bbo=True)["status"] == "REJECTED"


def test_hvr_0592_book_must_not_be_crossed():
    assert liquidity_crossed_book_receipt(best_bid=100.0, best_ask=101.0)["status"] == "PROVEN"
    assert liquidity_crossed_book_receipt(best_bid=101.0, best_ask=100.0)["status"] == "REJECTED"


def test_hvr_0593_sizes_must_be_positive():
    assert liquidity_negative_size_receipt(sizes=[1.0, 2.0])["status"] == "PROVEN"
    assert liquidity_negative_size_receipt(sizes=[1.0, -1.0])["status"] == "REJECTED"


def test_hvr_0594_prices_must_match_tick():
    assert liquidity_tick_receipt(prices=[100.0, 100.5], tick_size=0.5)["status"] == "PROVEN"
    assert liquidity_tick_receipt(prices=[100.1], tick_size=0.5)["status"] == "REJECTED"


def test_hvr_0595_delta_requires_snapshot():
    assert liquidity_delta_receipt(has_snapshot=True, delta_count=1)["status"] == "PROVEN"
    assert liquidity_delta_receipt(has_snapshot=False, delta_count=1)["status"] == "REJECTED"


def test_hvr_0596_stale_l2_is_rejected():
    assert liquidity_staleness_receipt(now_ms=1000, received_ts_ms=900, max_age_ms=100)["status"] == "PROVEN"
    assert liquidity_staleness_receipt(now_ms=1001, received_ts_ms=900, max_age_ms=100)["status"] == "REJECTED"


def test_hvr_0597_quantity_must_fit_depth():
    assert liquidity_quantity_receipt(requested_quantity=1.0, visible_depth=2.0)["status"] == "PROVEN"
    assert liquidity_quantity_receipt(requested_quantity=3.0, visible_depth=2.0)["status"] == "REJECTED"


def test_hvr_0598_consumption_is_once_only():
    assert liquidity_consumption_receipt(consumed_quantity=1.0, available_quantity=2.0, already_consumed=1.0)["status"] == "PROVEN"
    assert liquidity_consumption_receipt(consumed_quantity=2.0, available_quantity=2.0, already_consumed=1.0)["status"] == "REJECTED"


def test_hvr_0599_touch_only_is_not_maker_fill():
    assert liquidity_maker_touch_receipt(touched=True, executed=True)["status"] == "PROVEN"
    assert liquidity_maker_touch_receipt(touched=True, executed=False)["status"] == "REJECTED"


def test_hvr_0600_maker_fee_must_not_exceed_taker_fee():
    assert liquidity_fee_order_receipt(maker_fee_bps=1.0, taker_fee_bps=2.0)["status"] == "PROVEN"
    assert liquidity_fee_order_receipt(maker_fee_bps=3.0, taker_fee_bps=2.0)["status"] == "REJECTED"


def test_hvr_0601_liquidity_done_requires_all_proven_gates():
    checks = [
        liquidity_required_field_receipt({"coin": "BTC"}, field="coin"),
        liquidity_replay_receipt(outputs=[{"depth": 1}, {"depth": 1}]),
        liquidity_fee_order_receipt(maker_fee_bps=1.0, taker_fee_bps=2.0),
    ]
    assert liquidity_done_receipt(checks=checks)["status"] == "PROVEN"
    assert liquidity_done_receipt(checks=checks[:-1] + [{"status": "PROVEN"}])["status"] == "REJECTED"
