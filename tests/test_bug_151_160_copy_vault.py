from hl_observer.paper.partial_fill_model import (
    cash_delta_receipt,
    crossed_book_receipt,
    exit_fill_from_depth_receipt,
    market_depth_fill_receipt,
    market_status_receipt,
    minimum_notional_receipt,
    replay_fill_dedup_receipt,
    tick_aligned_price_receipt,
    visible_capacity_receipt,
)


def test_bug_151_buy_consumes_ask_not_bid():
    receipt = market_depth_fill_receipt(
        side="buy",
        order_notional_usdc=50,
        levels=[
            {"px": 99, "sz": 1, "book_side": "bid"},
            {"px": 101, "sz": 1, "book_side": "ask"},
        ],
    )
    assert receipt["vwap"] == 101


def test_bug_152_liquidation_uses_executable_exit_price():
    receipt = exit_fill_from_depth_receipt(
        side="sell", quantity=1, levels=[{"px": 99, "sz": 1, "book_side": "bid"}, {"px": 101, "sz": 1, "book_side": "ask"}]
    )
    assert receipt["vwap"] == 99


def test_bug_153_external_volume_is_removed_before_fill():
    receipt = market_depth_fill_receipt(
        side="buy",
        order_notional_usdc=100,
        levels=[{"px": 100, "sz": 1, "book_side": "ask", "native_id": "a"}],
        externally_consumed_by_id={"a": 0.75},
    )
    assert receipt["filled_notional_usdc"] == 25


def test_bug_154_partial_fill_updates_cash_once_with_fee():
    receipt = cash_delta_receipt(side="buy", filled_notional_usdc=50, fee_bps=10, cash_before_usdc=1000)
    assert receipt["cash_delta_usdc"] == -50.05
    assert receipt["cash_after_usdc"] == 949.95


def test_bug_155_rounding_cannot_bypass_minimum_notional():
    rejected = minimum_notional_receipt(raw_notional_usdc=10.01, rounded_notional_usdc=9.99, minimum_notional_usdc=10)
    accepted = minimum_notional_receipt(raw_notional_usdc=10.01, rounded_notional_usdc=10.01, minimum_notional_usdc=10)
    assert rejected["accepted"] is False
    assert accepted["accepted"] is True


def test_bug_156_slippage_price_must_respect_tick_size():
    assert tick_aligned_price_receipt(price=100.0, tick_size=0.1)["aligned"] is True
    assert tick_aligned_price_receipt(price=100.05, tick_size=0.1)["aligned"] is False


def test_bug_157_crossed_book_is_not_executable():
    receipt = crossed_book_receipt(bid=100, ask=99)
    assert receipt["valid"] is False


def test_bug_158_suspended_market_is_fail_closed():
    receipt = market_status_receipt(status="suspended")
    assert receipt["market_active"] is False


def test_bug_159_replay_deduplicates_native_fill_ids():
    receipt = replay_fill_dedup_receipt(fill_ids=["f1", "f1", "f2"])
    assert receipt["unique_fill_count"] == 2
    assert receipt["duplicate_count"] == 1


def test_bug_160_visible_capacity_exposes_invisible_remainder():
    receipt = visible_capacity_receipt(requested_notional_usdc=100, visible_levels=[{"px": 100, "sz": 0.5}])
    assert receipt["fully_visible"] is False
    assert receipt["remaining_invisible_usdc"] == 50
