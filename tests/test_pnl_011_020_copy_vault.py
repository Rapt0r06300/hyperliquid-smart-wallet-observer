"""PAPER/READ-ONLY accounting guards for Copy-Vault PNL-011..020.

These tests prove code-path invariants only.  They do not certify an economic
result or replace SAFE observations with fixtures.
"""

from __future__ import annotations

import math

import pytest

from hl_observer.backtesting.copy_vault_execution_math import _walk_quote_notional
from hl_observer.collection.vault_fills_backfill import pagination_boundary_receipt
from hl_observer.paper_trading.canonical_execution import (
    CausalMarketSnapshot,
    PaperExecutionIntent,
    execute_paper_intent,
)
from hl_observer.paper_trading.exec_model import simulate_depth_execution, simulate_execution
from hl_observer.paper_trading.execution_truth import ExecutionTruth
from hl_observer.paper_trading.liquidity_consumption import LiquidityConsumptionLedger
from hl_observer.simulation.accounting_truth import finite_number
from hl_observer.simulation.capital_accounting import equity_after_fill_fee_receipt
from hl_observer.simulation.cost_components import decompose_execution
from hl_observer.simulation.fee_model import compute_fee_usdc, fee_tier_validity_receipt
from hl_observer.simulation.funding_payment_tracker import funding_boundary_receipt


NOW_MS = 1_800_000_000_000


def _truth() -> ExecutionTruth:
    return ExecutionTruth.from_levels(
        coin="HYPE",
        bids=((99.0, 1.0),),
        asks=((100.0, 1.0),),
        received_ts_ms=NOW_MS,
        exchange_ts_ms=NOW_MS - 1,
        source="recorded_hyperliquid_l2",
        snapshot_id="pnl-011-020-book",
        data_origin="RECORDED_REAL",
    )


def _intent(name: str, *, notional: float = 60.0) -> PaperExecutionIntent:
    return PaperExecutionIntent(
        strategy_id=name,
        coin="HYPE",
        position_side="LONG",
        action="OPEN",
        target_notional_usdc=notional,
        confidence=0.95,
        created_at_ms=NOW_MS,
    )


def test_pnl011_charges_entry_and_each_partial_exit() -> None:
    entry_fee = compute_fee_usdc(100.0, 4.5)
    partial_a = compute_fee_usdc(40.0, 4.5)
    partial_b = compute_fee_usdc(60.0, 4.5)

    assert entry_fee == pytest.approx(0.045)
    assert partial_a + partial_b == pytest.approx(entry_fee)
    assert entry_fee + partial_a + partial_b == pytest.approx(0.09)


def test_pnl012_rejects_nan_infinity_and_boolean_accounting_inputs() -> None:
    assert finite_number(True) is None
    assert finite_number(float("nan")) is None
    assert finite_number(float("inf")) is None
    with pytest.raises(ValueError):
        compute_fee_usdc(True, 4.5)  # type: ignore[arg-type]
    receipt = fee_tier_validity_receipt(
        fee_bps=True,
        valid_from_epoch_ms=1_000,
        valid_until_epoch_ms=None,
        as_of_epoch_ms=1_001,
        source="canonical",
    )
    assert receipt["status"] == "UNMEASURABLE"


def test_pnl013_funding_is_charged_only_after_the_settlement_boundary() -> None:
    before_boundary = funding_boundary_receipt(
        side="LONG",
        notional_usdc=1_000,
        funding_rate=0.001,
        opened_at_ms=100,
        settlement_at_ms=200,
        closed_at_ms=200,
    )
    after_boundary = funding_boundary_receipt(
        side="LONG",
        notional_usdc=1_000,
        funding_rate=0.001,
        opened_at_ms=100,
        settlement_at_ms=200,
        closed_at_ms=201,
    )

    assert before_boundary["status"] == "PROVEN"
    assert before_boundary["crossed_settlement"] is False
    assert before_boundary["payment_usdc"] == 0.0
    assert after_boundary["crossed_settlement"] is True
    assert after_boundary["payment_usdc"] == -1.0


def test_pnl014_touching_maker_price_is_not_a_maker_fill_without_queue_evidence() -> None:
    no_queue = simulate_execution(
        side="BUY",
        notional_usdc=60.0,
        mid_price=100.0,
        is_maker=True,
        top_depth_usdc=100.0,
    )
    queued = simulate_execution(
        side="BUY",
        notional_usdc=60.0,
        mid_price=100.0,
        is_maker=True,
        top_depth_usdc=100.0,
        queue_depletion_usdc=60.0,
    )

    assert no_queue.reason == "NO_FILL_NO_QUEUE_EVIDENCE"
    assert no_queue.filled_notional_usdc == 0.0
    assert queued.is_maker is True
    assert queued.filled_notional_usdc == 60.0


def test_pnl015_two_plans_consume_distinct_visible_depth() -> None:
    ledger = LiquidityConsumptionLedger()
    truth = _truth()
    snapshot = CausalMarketSnapshot.from_truth(truth, decision_ts_ms=NOW_MS)

    first = execute_paper_intent(_intent("first"), snapshot, liquidity_ledger=ledger)
    second = execute_paper_intent(_intent("second"), snapshot, liquidity_ledger=ledger)

    assert first.execution.filled_notional_usdc == 60.0
    assert second.execution.filled_notional_usdc == 40.0
    assert second.execution.partial is True
    assert first.execution.filled_quantity + second.execution.filled_quantity == 1.0


def test_pnl016_visible_l2_exhaustion_is_partial_not_invented_depth() -> None:
    result = simulate_depth_execution(
        side="BUY",
        notional_usdc=150.0,
        mid_price=100.0,
        asks=[(100.0, 1.0)],
        min_fill_ratio=0.85,
    )

    assert result.filled_notional_usdc == 100.0
    assert result.missed_notional_usdc == 50.0
    assert result.fill_ratio == pytest.approx(2 / 3)
    assert result.missed is True
    assert result.reason == "MISSED_FILL"


def test_pnl017_same_timestamp_requires_native_identity_for_each_fill() -> None:
    retained = pagination_boundary_receipt(
        [[{"ts_ms": 1_000, "tid": "a", "coin": "BTC"}],
         [{"ts_ms": 1_000, "tid": "b", "coin": "BTC"}]]
    )
    missing_identity = pagination_boundary_receipt(
        [[{"ts_ms": 1_000, "coin": "BTC"}]]
    )

    assert retained["status"] == "PROVEN"
    assert retained["retained_count"] == 2
    assert missing_identity["status"] == "UNMEASURABLE"
    assert missing_identity["reason"] == "BOUNDARY_IDENTITY_MISSING"


def test_pnl018_low_capital_keeps_decimal_quantity_and_rejects_invalid_precision() -> None:
    vwap, quantity = _walk_quote_notional(
        [("100.01", "1.0")],
        0.01,
    ) or (None, None)

    assert vwap == pytest.approx(100.01)
    assert quantity == pytest.approx(0.01 / 100.01)
    invalid = simulate_depth_execution(
        side="BUY",
        notional_usdc=True,  # type: ignore[arg-type]
        mid_price=100.0,
        asks=[(100.01, 1.0)],
    )
    assert invalid.reason == "INVALID_REQUEST"
    assert invalid.filled_notional_usdc == 0.0


def test_pnl019_available_equity_is_reduced_by_the_opening_fee() -> None:
    receipt = equity_after_fill_fee_receipt(
        starting_equity_usd=200.0,
        realized_pnl_usd=1.0,
        fee_usd=0.2,
    )
    missing_fee = equity_after_fill_fee_receipt(
        starting_equity_usd=200.0,
        realized_pnl_usd=1.0,
        fee_usd=float("nan"),
    )

    assert receipt == {"status": "PROVEN", "equity_usd": 200.8, "real_execution": False}
    assert missing_fee["status"] == "UNMEASURABLE"


def test_pnl020_execution_price_comes_from_observed_touch_not_leader_mid() -> None:
    result = simulate_depth_execution(
        side="BUY",
        notional_usdc=100.0,
        mid_price=100.0,
        asks=[(101.0, 2.0)],
    )

    assert result.average_fill_price == 101.0
    assert result.average_fill_price != 100.0
    assert math.isfinite(result.average_fill_price)

