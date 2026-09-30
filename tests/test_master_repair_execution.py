from __future__ import annotations

import math

import pytest

from hl_observer.paper_trading.exec_model import (
    book_notional_for_quantity,
    simulate_execution,
)
from hl_observer.paper_trading.execution_truth import ExecutionTruth
from hl_observer.paper_trading.paper_engine import PaperEngine, PaperEngineConfig
from hl_observer.position_lifecycle.reconstructor import LifecycleAction
from hl_observer.signals.leader_delta import LeaderDelta


def _truth(
    *,
    bids: tuple[tuple[float, float], ...] = ((99.0, 1.0),),
    asks: tuple[tuple[float, float], ...] = ((101.0, 1.0),),
) -> ExecutionTruth:
    return ExecutionTruth.from_levels(
        coin="HYPE",
        bids=bids,
        asks=asks,
        exchange_ts_ms=1_000,
        received_ts_ms=1_010,
        source="unit:l2Book",
    )


def test_live_maker_never_assumes_full_fill_without_queue_evidence() -> None:
    result = simulate_execution(
        side="BUY",
        notional_usdc=100.0,
        mid_price=100.0,
        is_maker=True,
        execution_truth=_truth(),
        decision_ts_ms=1_020,
        strict_book=True,
    )
    assert result.filled_notional_usdc == 0.0
    assert result.missed_notional_usdc == 100.0
    assert result.fill_price is None
    assert result.reason == "NO_FILL_NO_QUEUE_EVIDENCE"


def test_live_maker_no_fill_when_queue_not_depleted() -> None:
    result = simulate_execution(
        side="BUY",
        notional_usdc=100.0,
        mid_price=100.0,
        is_maker=True,
        queue_ahead_usdc=200.0,
        queue_depletion_usdc=199.0,
        adverse_selection_bps=1.0,
        execution_truth=_truth(),
        decision_ts_ms=1_020,
        strict_book=True,
    )
    assert result.fill_ratio == 0.0
    assert result.reason == "NO_FILL_QUEUE_NOT_DEPLETED"


def test_live_maker_partial_fill_propagates_every_accounting_field() -> None:
    result = simulate_execution(
        side="BUY",
        notional_usdc=100.0,
        mid_price=100.0,
        is_maker=True,
        queue_ahead_usdc=50.0,
        queue_depletion_usdc=80.0,
        adverse_selection_bps=2.0,
        execution_truth=_truth(),
        decision_ts_ms=1_020,
        strict_book=True,
    )
    assert result.requested_notional_usdc == 100.0
    assert result.filled_notional_usdc == 30.0
    assert result.notional_usdc == 30.0
    assert result.missed_notional_usdc == 70.0
    assert result.fill_ratio == 0.3
    assert result.partial and result.missed
    assert result.fill_price is not None
    assert result.net_cost_bps is not None


def test_taker_depth_partial_fill_propagates_exactly() -> None:
    truth = _truth(asks=((101.0, 0.5),), bids=((99.0, 1.0),))
    result = simulate_execution(
        side="BUY",
        notional_usdc=100.0,
        mid_price=100.0,
        execution_truth=truth,
        decision_ts_ms=1_020,
        strict_book=True,
    )
    assert result.requested_notional_usdc == 100.0
    assert result.filled_notional_usdc == pytest.approx(50.5)
    assert result.missed_notional_usdc == pytest.approx(49.5)
    assert result.notional_usdc == result.filled_notional_usdc
    assert result.partial
    assert result.execution_snapshot_id == truth.snapshot_id


def test_execution_uses_real_l2_capacity() -> None:
    truth = _truth(
        bids=((99.0, 1.0),),
        asks=((101.0, 0.25), (102.0, 0.25)),
    )
    result = simulate_execution(
        side="BUY",
        notional_usdc=100.0,
        mid_price=100.0,
        execution_truth=truth,
        decision_ts_ms=1_020,
        strict_book=True,
    )
    assert result.filled_notional_usdc == pytest.approx(50.75)
    assert result.fill_price is not None and result.fill_price > 101.0
    assert result.cost_status == "MEASURED"


def test_exit_quantity_walk_uses_exact_visible_levels_and_preserves_remainder() -> None:
    truth = _truth(
        bids=((99.0, 0.4), (98.0, 0.6)),
        asks=((101.0, 2.0),),
    )
    requested = book_notional_for_quantity(
        truth,
        side="SELL",
        quantity=0.75,
        fallback_price=100.0,
    )
    assert requested == pytest.approx(0.4 * 99.0 + 0.35 * 98.0)

    result = simulate_execution(
        side="SELL",
        notional_usdc=requested,
        mid_price=truth.mid_price,
        execution_truth=truth,
        decision_ts_ms=1_020,
        strict_book=True,
    )
    assert result.filled_quantity == pytest.approx(0.75)
    assert result.execution_snapshot_id == truth.snapshot_id

    visible_only = book_notional_for_quantity(
        truth,
        side="SELL",
        quantity=2.0,
        fallback_price=100.0,
    )
    partial = simulate_execution(
        side="SELL",
        notional_usdc=visible_only,
        mid_price=truth.mid_price,
        execution_truth=truth,
        decision_ts_ms=1_020,
        strict_book=True,
    )
    assert partial.filled_quantity == pytest.approx(1.0)
    assert 2.0 - partial.filled_quantity == pytest.approx(1.0)


def test_missing_live_book_blocks_strict_open() -> None:
    result = simulate_execution(
        side="BUY",
        notional_usdc=100.0,
        mid_price=100.0,
        top_depth_usdc=1_000_000.0,
        strict_book=True,
    )
    assert result.reason == "NO_LIVE_EXECUTABLE_BOOK"
    assert result.filled_notional_usdc == 0.0


def test_degraded_constant_costs_never_enter_strict_pnl() -> None:
    approximate = simulate_execution(
        side="BUY",
        notional_usdc=100.0,
        mid_price=100.0,
        top_depth_usdc=50_000.0,
    )
    strict = simulate_execution(
        side="BUY",
        notional_usdc=100.0,
        mid_price=100.0,
        top_depth_usdc=50_000.0,
        strict_book=True,
    )
    assert approximate.cost_status == "APPROXIMATE"
    assert strict.cost_status == "UNMEASURABLE"
    assert strict.fill_price is None


def test_unknown_cost_is_not_zero() -> None:
    result = simulate_execution(
        side="BUY",
        notional_usdc=100.0,
        mid_price=100.0,
        is_maker=True,
        queue_depletion_usdc=100.0,
        execution_truth=_truth(),
        decision_ts_ms=1_020,
        strict_book=True,
    )
    assert result.filled_notional_usdc == 100.0
    assert result.adverse_selection_bps is None
    assert result.net_cost_bps is None
    assert result.cost_status == "UNMEASURABLE"


def test_execution_costs_are_counted_exactly_once() -> None:
    wallet = "0x" + "a" * 40
    engine = PaperEngine(config=PaperEngineConfig(max_position_usdt=100.0))
    opened_delta = LeaderDelta(
        delta_id="cost-open",
        wallet=wallet,
        coin="HYPE",
        action=LifecycleAction.OPEN_LONG,
        previous_size=0.0,
        current_size=1.0,
        delta_size=1.0,
        observed_at_ms=1_020,
        leader_event_time_ms=1_000,
        source="unit_test",
        confidence=0.95,
        evidence_ref="fill:open",
    )
    opened = engine.apply_delta(
        opened_delta,
        market_price=100.0,
        observed_at_ms=1_020,
        edge_remaining_bps=90.0,
        spread_bps=1.0,
        estimated_slippage_bps=1.0,
        wallet_score=95.0,
        signal_score=90.0,
        marks={"HYPE": 100.0},
        top_depth_usdt=None,
        execution_truth=_truth(bids=((99.0, 10_000.0),), asks=((101.0, 10_000.0),)),
    )
    assert opened.accepted and opened.trade is not None and opened.position is not None
    opened_quantity = opened.position.quantity
    opened_fill = opened.trade.fill_price
    assert opened_fill is not None and opened_fill > 101.0

    closed_delta = LeaderDelta(
        delta_id="cost-close",
        wallet=wallet,
        coin="HYPE",
        action=LifecycleAction.CLOSE_LONG,
        previous_size=1.0,
        current_size=0.0,
        delta_size=-1.0,
        observed_at_ms=1_120,
        leader_event_time_ms=1_100,
        source="unit_test",
        confidence=0.95,
        evidence_ref="fill:close",
    )
    closed = engine.apply_delta(
        closed_delta,
        market_price=105.0,
        observed_at_ms=1_120,
        edge_remaining_bps=90.0,
        spread_bps=1.0,
        estimated_slippage_bps=1.0,
        wallet_score=95.0,
        signal_score=90.0,
        marks={"HYPE": 105.0},
        top_depth_usdt=None,
        execution_truth=ExecutionTruth.from_levels(
            coin="HYPE",
            bids=((104.0, 10_000.0),),
            asks=((106.0, 10_000.0),),
            exchange_ts_ms=1_100,
            received_ts_ms=1_110,
            source="unit:l2Book",
        ),
    )

    assert closed.accepted and closed.trade is not None
    assert closed.trade.fill_price is not None and closed.trade.fill_price < 104.0
    expected = (closed.trade.fill_price - opened_fill) * opened_quantity
    assert closed.realized_pnl_usdt == pytest.approx(expected)
    assert engine.realized_pnl_usdt == pytest.approx(expected)
    assert closed.ledger_snapshot is not None
    assert closed.ledger_snapshot["realized_pnl_usdc"] == pytest.approx(expected)


@pytest.mark.parametrize("value", [0.0, -1.0, math.nan, math.inf, -math.inf])
def test_invalid_numeric_inputs_never_mutate_state(value: float) -> None:
    with pytest.raises(ValueError):
        simulate_execution(
            side="BUY",
            notional_usdc=value,
            mid_price=100.0,
        )
