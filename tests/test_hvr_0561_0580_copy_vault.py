from hl_observer.paper_trading.latency_truth import (
    ASSUMED,
    latency_age_receipt,
    latency_consumption_receipt,
    latency_crossed_book_receipt,
    latency_cutoff_receipt,
    latency_delta_receipt,
    latency_depth_receipt,
    latency_duplicate_receipt,
    latency_fee_order_receipt,
    latency_finite_receipt,
    latency_field_type_receipt,
    latency_maker_touch_receipt,
    latency_negative_size_receipt,
    latency_null_field_receipt,
    latency_quantity_receipt,
    latency_replay_receipt,
    latency_required_field_receipt,
    latency_retry_receipt,
    latency_staleness_receipt,
    latency_tick_receipt,
    latency_truth_safety_receipt,
    latency_truth_done_receipt,
    verite_latence,
)


def _latency_truth():
    return verite_latence(
        [{"observed_at_ms": 1100, "mid": 101.0}],
        decision_ts_ms=1000,
        mid_decision=100.0,
        side="BUY",
        delay_ms=100,
        delay_source=ASSUMED,
    )


def test_hvr_0561_latency_truth_baseline_is_safe():
    assert latency_truth_safety_receipt(_latency_truth())["status"] == "PROVEN"
    assert latency_truth_safety_receipt({"real_execution": True})["status"] == "REJECTED"


def test_hvr_0562_required_field():
    assert latency_required_field_receipt({"coin": "BTC"}, field="coin")["status"] == "PROVEN"
    assert latency_required_field_receipt({}, field="coin")["status"] == "REJECTED"


def test_hvr_0563_null_field():
    assert latency_null_field_receipt({"coin": "BTC"}, field="coin")["status"] == "PROVEN"
    assert latency_null_field_receipt({"coin": None}, field="coin")["status"] == "REJECTED"


def test_hvr_0564_field_type():
    assert latency_field_type_receipt({"depth": 1.0}, field="depth", expected_type=float)["status"] == "PROVEN"
    assert latency_field_type_receipt({"depth": "1"}, field="depth", expected_type=float)["status"] == "REJECTED"


def test_hvr_0565_finite_value():
    assert latency_finite_receipt(1.5)["status"] == "PROVEN"
    assert latency_finite_receipt(float("nan"))["status"] == "REJECTED"


def test_hvr_0566_cutoff():
    assert latency_cutoff_receipt(event_ts_ms=10, cutoff_ts_ms=10)["status"] == "PROVEN"
    assert latency_cutoff_receipt(event_ts_ms=11, cutoff_ts_ms=10)["status"] == "REJECTED"


def test_hvr_0567_age():
    assert latency_age_receipt(event_ts_ms=10, oldest_allowed_ts_ms=10)["status"] == "PROVEN"
    assert latency_age_receipt(event_ts_ms=9, oldest_allowed_ts_ms=10)["status"] == "REJECTED"


def test_hvr_0568_duplicate_events():
    assert latency_duplicate_receipt(event_ids=["a", "b"])["status"] == "PROVEN"
    assert latency_duplicate_receipt(event_ids=["a", "a"])["status"] == "REJECTED"


def test_hvr_0569_bounded_retry_requires_checkpoint():
    assert latency_retry_receipt(attempts=2, max_attempts=3, checkpoint_saved=True)["status"] == "PROVEN"
    assert latency_retry_receipt(attempts=4, max_attempts=3, checkpoint_saved=True)["status"] == "REJECTED"


def test_hvr_0570_replay_is_deterministic():
    assert latency_replay_receipt(outputs=[{"mid": 100}, {"mid": 100}])["status"] == "PROVEN"
    assert latency_replay_receipt(outputs=[{"mid": 100}, {"mid": 101}])["status"] == "REJECTED"


def test_hvr_0571_full_depth_is_not_bbo():
    assert latency_depth_receipt(bids=[(100.0, 1.0)], asks=[(101.0, 1.0)], is_bbo=False)["status"] == "PROVEN"
    assert latency_depth_receipt(bids=[(100.0, 1.0)], asks=[(101.0, 1.0)], is_bbo=True)["status"] == "REJECTED"


def test_hvr_0572_book_must_not_be_crossed():
    assert latency_crossed_book_receipt(best_bid=100.0, best_ask=101.0)["status"] == "PROVEN"
    assert latency_crossed_book_receipt(best_bid=101.0, best_ask=100.0)["status"] == "REJECTED"


def test_hvr_0573_sizes_must_be_positive():
    assert latency_negative_size_receipt(sizes=[1.0, 2.0])["status"] == "PROVEN"
    assert latency_negative_size_receipt(sizes=[1.0, -1.0])["status"] == "REJECTED"


def test_hvr_0574_prices_must_match_tick():
    assert latency_tick_receipt(prices=[100.0, 100.5], tick_size=0.5)["status"] == "PROVEN"
    assert latency_tick_receipt(prices=[100.1], tick_size=0.5)["status"] == "REJECTED"


def test_hvr_0575_delta_requires_snapshot():
    assert latency_delta_receipt(has_snapshot=True, delta_count=1)["status"] == "PROVEN"
    assert latency_delta_receipt(has_snapshot=False, delta_count=1)["status"] == "REJECTED"


def test_hvr_0576_stale_l2_is_rejected():
    assert latency_staleness_receipt(now_ms=1000, received_ts_ms=900, max_age_ms=100)["status"] == "PROVEN"
    assert latency_staleness_receipt(now_ms=1001, received_ts_ms=900, max_age_ms=100)["status"] == "REJECTED"


def test_hvr_0577_quantity_must_fit_depth():
    assert latency_quantity_receipt(requested_quantity=1.0, visible_depth=2.0)["status"] == "PROVEN"
    assert latency_quantity_receipt(requested_quantity=3.0, visible_depth=2.0)["status"] == "REJECTED"


def test_hvr_0578_consumption_is_once_only():
    assert latency_consumption_receipt(consumed_quantity=1.0, available_quantity=2.0, already_consumed=1.0)["status"] == "PROVEN"
    assert latency_consumption_receipt(consumed_quantity=2.0, available_quantity=2.0, already_consumed=1.0)["status"] == "REJECTED"


def test_hvr_0579_touch_only_is_not_maker_fill():
    assert latency_maker_touch_receipt(touched=True, executed=True)["status"] == "PROVEN"
    assert latency_maker_touch_receipt(touched=True, executed=False)["status"] == "REJECTED"


def test_hvr_0580_maker_fee_must_not_exceed_taker_fee():
    assert latency_fee_order_receipt(maker_fee_bps=1.0, taker_fee_bps=2.0)["status"] == "PROVEN"
    assert latency_fee_order_receipt(maker_fee_bps=3.0, taker_fee_bps=2.0)["status"] == "REJECTED"


def test_hvr_0581_latency_truth_done_requires_all_proven_gates():
    assert latency_truth_done_receipt(
        status="PROVEN", coverage_status="PROVEN", proof_ids=["latency-proof"], replay_verified=True
    )["status"] == "PROVEN"
    assert latency_truth_done_receipt(
        status="PROVEN", coverage_status="PROVEN", proof_ids=[], replay_verified=True
    )["status"] == "REJECTED"
