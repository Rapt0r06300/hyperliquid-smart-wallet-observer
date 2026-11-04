from hl_observer.hyperliquid.schemas import RiskDecision, SignalCandidate, SignalDecision
from hl_observer.paper.paper_executor import PaperExecutor
from hl_observer.paper.partial_fill_model import (
    acceptance_before_fill,
    limit_order_priority_receipt,
    liquidity_allocation_receipt,
    maker_queue_fill_receipt,
    market_depth_fill_receipt,
    market_impact_receipt,
)


def test_bug_141_missing_depth_is_not_a_fill():
    receipt = market_depth_fill_receipt(side="buy", order_notional_usdc=100, levels=[])
    assert receipt["status"] == "UNMEASURABLE"
    assert receipt["filled"] is False


def test_bug_142_fill_cannot_precede_acceptance():
    assert acceptance_before_fill(accepted_ts_ms=100, fill_ts_ms=99)["accepted"] is False
    assert acceptance_before_fill(accepted_ts_ms=100, fill_ts_ms=100)["accepted"] is True


def test_bug_143_uses_filled_not_requested_notional():
    receipt = market_depth_fill_receipt(
        side="buy", order_notional_usdc=200, levels=[{"px": 100, "sz": 0.5}]
    )
    assert receipt["filled_notional_usdc"] == 50.0
    assert receipt["partial"] is True


def test_bug_144_uses_executable_price_not_midpoint():
    buy = market_depth_fill_receipt(side="buy", order_notional_usdc=50, levels=[{"px": 101, "sz": 1}])
    sell = market_depth_fill_receipt(side="sell", order_notional_usdc=50, levels=[{"px": 99, "sz": 1}])
    assert buy["vwap"] == 101
    assert sell["vwap"] == 99


def test_bug_145_impact_increases_with_order_size():
    small = market_impact_receipt(order_notional_usdc=10, visible_depth_usdc=100)
    large = market_impact_receipt(order_notional_usdc=100, visible_depth_usdc=100)
    assert large["impact_bps"] > small["impact_bps"]


def test_bug_146_maker_queue_must_be_consumed_before_fill():
    blocked = maker_queue_fill_receipt(touched=True, queue_ahead_usdc=10, consumed_usdc=5, order_notional_usdc=10)
    filled = maker_queue_fill_receipt(touched=True, queue_ahead_usdc=10, consumed_usdc=15, order_notional_usdc=10)
    assert blocked["filled"] is False
    assert filled["filled"] is True


def test_bug_147_cancelled_depth_row_cannot_fill():
    receipt = market_depth_fill_receipt(
        side="buy", order_notional_usdc=10, levels=[{"px": 100, "sz": 1, "status": "cancelled"}]
    )
    assert receipt["status"] == "UNMEASURABLE"
    assert receipt["filled"] is False


def test_bug_148_price_or_time_modification_resets_maker_priority():
    receipt = limit_order_priority_receipt(
        original_price=100, modified_price=101, original_ts_ms=10, modified_ts_ms=11
    )
    assert receipt["queue_reset"] is True
    assert receipt["maker_priority"] == "RESET"


def test_bug_149_allocates_one_liquidity_budget_once_per_signal():
    receipt = liquidity_allocation_receipt(
        requests=[
            {"signal_id": "s", "notional_usdc": 80},
            {"signal_id": "s", "notional_usdc": 80},
            {"signal_id": "t", "notional_usdc": 80},
        ],
        available_notional_usdc=100,
    )
    assert receipt["allocations"] == {"s": 80.0, "t": 20.0}


def test_bug_150_sell_consumes_bid_depth():
    receipt = market_depth_fill_receipt(
        side="sell",
        order_notional_usdc=99,
        levels=[{"px": 99, "sz": 1, "book_side": "bid"}, {"px": 101, "sz": 1, "book_side": "ask"}],
    )
    assert receipt["vwap"] == 99


def test_explicit_depth_path_refuses_missing_evidence_and_records_actual_fill():
    signal = SignalCandidate(
        id="bug141-150",
        source_wallet="0xabc",
        coin="BTC",
        side="long",
        signal_type="open",
        observed_price=100,
        timestamp_ms=1,
        signal_age_ms=100,
    )
    risk = RiskDecision(allowed=True, decision=SignalDecision.PAPER_TRADE, reasons=[], gates={"all": True})
    executor = PaperExecutor()
    rejected = executor.submit(signal, risk, notional_usdc=10, market_depth=[], accepted_ts_ms=1, fill_ts_ms=2)
    assert rejected.notional_usdc == 0
    filled = executor.submit(
        signal,
        risk,
        notional_usdc=100,
        market_depth=[{"px": 101, "sz": 0.5}],
        accepted_ts_ms=1,
        fill_ts_ms=2,
    )
    assert filled.notional_usdc == 50.5
