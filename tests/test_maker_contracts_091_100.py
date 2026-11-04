from __future__ import annotations

from hl_observer.backtesting.execution_passive_agressive import same_context_execution_receipt
from hl_observer.backtesting.maker_rebate_decision import rebate_without_fill_receipt
from hl_observer.backtesting.missed_fill_model import cancellation_uncertainty_receipt
from hl_observer.backtesting.queue_model import maker_fill_bound_receipt, reconcile_trade_and_delta_receipt
from hl_observer.paper.partial_fill_model import maker_partial_fill_receipt
from hl_observer.paper.pessimistic_fill_model import touch_only_fill_receipt
from hl_observer.paper.rejection_model import stale_order_cancellation_receipt
from hl_observer.research.maker_toxicity import maker_toxicity_receipt
from hl_observer.research.queue_model import queue_model_limits_receipt


def test_091_touch_is_not_fill() -> None:
    result = touch_only_fill_receipt(side="BUY", touched=True, observed_price=100.0, spread_bps=2.0, slippage_bps=3.0)
    assert result["status"] == "PROVEN"
    assert result["filled"] is False


def test_092_maker_fill_is_bounded_by_queue() -> None:
    result = maker_fill_bound_receipt(queue_ahead=10.0, trade_volume=5.0, observed_l2_delta=-8.0)
    assert result["status"] == "PROVEN"
    assert result["fill_upper_bound"] is False
    assert result["double_counting"] is False


def test_093_trade_and_delta_are_counted_once() -> None:
    result = reconcile_trade_and_delta_receipt(book_change=-8.0, trade_volume=5.0)
    assert result["status"] == "PROVEN"
    assert result["net_cancellation"] == 3.0
    assert result["counted_once"] is True


def test_094_maker_taker_use_same_context() -> None:
    result = same_context_execution_receipt(edge_bps=50.0, adverse_move_bps=10.0, maker_cost_bps=2.0, taker_cost_bps=8.0)
    assert result["status"] == "PROVEN"
    assert result["maker_edge_bps"] == 38.0
    assert result["taker_edge_bps"] == 32.0


def test_095_stale_paper_order_is_cancelled() -> None:
    result = stale_order_cancellation_receipt(age_ms=2_000, max_age_ms=1_000, state="OPEN")
    assert result["status"] == "PROVEN"
    assert result["cancel"] is True


def test_096_maker_partial_fill_uses_observed_depth() -> None:
    result = maker_partial_fill_receipt(order_notional_usdc=100.0, observed_depth_usdc=40.0)
    assert result["status"] == "PROVEN"
    assert result["fill_ratio"] == 0.4
    assert result["partial"] is True


def test_097_maker_toxicity_requires_all_observations() -> None:
    result = maker_toxicity_receipt(aggr_flow_norm=0.2, absorption=0.3, queue_depletion=0.4, microprice_tilt_bps=1.0, spread_widening=0.1)
    assert result["status"] == "PROVEN"
    assert result["toxicity"] > 0.0


def test_098_missing_cancellation_is_not_certified() -> None:
    result = cancellation_uncertainty_receipt(age_ms=2_000, max_age_ms=1_000, partial_ratio=0.0, cancel_observed=None)
    assert result["status"] == "UNMEASURABLE"


def test_099_rebate_is_zero_without_fill() -> None:
    result = rebate_without_fill_receipt(prob_fill=0.5, rebate_bps=2.0, selection_adverse_bps=1.0)
    assert result["status"] == "PROVEN"
    assert result["no_fill_rebate"] == 0.0


def test_100_queue_model_limits_are_explicit() -> None:
    result = queue_model_limits_receipt(queue_ahead=10.0, volume_traversant=5.0, cancels_devant=1.0)
    assert result["status"] == "PROVEN"
    assert result["paper_only"] is True
