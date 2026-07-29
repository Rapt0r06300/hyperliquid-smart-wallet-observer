from __future__ import annotations

from hl_observer.paper_trading.canonical_execution import (
    CausalMarketSnapshot,
    PaperExecutionIntent,
    execute_paper_intent,
)
from hl_observer.paper_trading.execution_truth import ExecutionTruth
from hl_observer.paper_trading.liquidity_consumption import (
    LiquidityConsumptionLedger,
)


NOW_MS = 1_800_000_000_000


def _truth(
    *,
    snapshot_id: str = "book:one",
    source: str = "hyperliquid",
) -> ExecutionTruth:
    return ExecutionTruth.from_levels(
        coin="HYPE",
        bids=((99.0, 1.0),),
        asks=((100.0, 1.0),),
        received_ts_ms=NOW_MS,
        exchange_ts_ms=NOW_MS - 1,
        source=source,
        snapshot_id=snapshot_id,
        data_origin="RECORDED_REAL",
    )


def _intent(
    name: str,
    *,
    side: str = "LONG",
    action: str = "OPEN",
    notional: float = 60.0,
) -> PaperExecutionIntent:
    return PaperExecutionIntent(
        strategy_id=name,
        coin="HYPE",
        position_side=side,
        action=action,
        target_notional_usdc=notional,
        confidence=0.95,
        created_at_ms=NOW_MS,
    )


def _execute(
    intent: PaperExecutionIntent,
    truth: ExecutionTruth,
    ledger: LiquidityConsumptionLedger,
):
    return execute_paper_intent(
        intent,
        CausalMarketSnapshot.from_truth(truth, decision_ts_ms=NOW_MS),
        liquidity_ledger=ledger,
    )


def test_two_plans_cannot_overfill_the_same_visible_ask() -> None:
    ledger = LiquidityConsumptionLedger()
    truth = _truth()

    first = _execute(_intent("first"), truth, ledger)
    second = _execute(_intent("second"), truth, ledger)
    exhausted = _execute(_intent("third"), truth, ledger)

    assert first.execution.filled_notional_usdc == 60.0
    assert second.execution.filled_notional_usdc == 40.0
    assert second.execution.partial is True
    assert exhausted.execution.filled_notional_usdc == 0.0
    assert exhausted.execution.reason == "LIQUIDITY_ALREADY_CONSUMED"
    assert (
        first.execution.filled_quantity
        + second.execution.filled_quantity
        + exhausted.execution.filled_quantity
        == 1.0
    )
    assert ledger.consumed_quantity(
        venue="hyperliquid",
        snapshot_id=truth.snapshot_id,
        coin="HYPE",
        execution_side="BUY",
        price=100.0,
    ) == 1.0


def test_same_plan_retry_is_idempotent() -> None:
    ledger = LiquidityConsumptionLedger()
    truth = _truth()
    intent = _intent("retry")

    first = _execute(intent, truth, ledger)
    retry = _execute(intent, truth, ledger)

    assert retry.execution == first.execution
    assert retry.liquidity_reservation is not None
    assert retry.liquidity_reservation.replayed is True
    assert len(ledger.snapshot()) == 1
    assert ledger.snapshot()[0].consumed_quantity == 0.6


def test_new_snapshot_and_other_venue_have_independent_liquidity() -> None:
    ledger = LiquidityConsumptionLedger()
    first = _execute(_intent("first"), _truth(), ledger)
    new_snapshot = _execute(
        _intent("new-snapshot"),
        _truth(snapshot_id="book:two"),
        ledger,
    )
    other_venue = _execute(
        _intent("other-venue"),
        _truth(source="recorded-replay"),
        ledger,
    )

    assert first.execution.filled_notional_usdc == 60.0
    assert new_snapshot.execution.filled_notional_usdc == 60.0
    assert other_venue.execution.filled_notional_usdc == 60.0


def test_buy_and_sell_consumption_are_independent() -> None:
    ledger = LiquidityConsumptionLedger()
    truth = _truth()

    buy = _execute(_intent("buy"), truth, ledger)
    sell = _execute(
        _intent("sell", side="LONG", action="CLOSE"),
        truth,
        ledger,
    )

    assert buy.plan.execution_side == "BUY"
    assert sell.plan.execution_side == "SELL"
    assert buy.execution.filled_quantity == 0.6
    assert abs(sell.execution.filled_quantity - (60.0 / 99.0)) < 1e-12
    assert {row.execution_side for row in ledger.snapshot()} == {"BUY", "SELL"}
