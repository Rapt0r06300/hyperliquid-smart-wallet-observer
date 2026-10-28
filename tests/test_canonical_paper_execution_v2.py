from __future__ import annotations

import pytest

from hl_observer.paper_trading.canonical_execution import (
    CausalMarketSnapshot,
    PaperExecutionIntent,
    execute_paper_intent,
)
from hl_observer.paper_trading.execution_truth import ExecutionTruth
from hl_observer.paper_trading.paper_connector import PaperSimConnector
from hl_observer.paper_trading.paper_engine import PaperEngine, PaperEngineConfig
from hl_observer.position_lifecycle.reconstructor import LifecycleAction
from hl_observer.signals.leader_delta import LeaderDelta
from hl_observer.strategies.models import (
    IntentAction,
    IntentSide,
    PaperIntent,
    approve_with_risk,
)

WALLET = "0x" + "c" * 40
OBSERVED_AT_MS = 1_800_000_000_000
BIDS = ((99.99, 100.0), (99.98, 100.0))
ASKS = ((100.01, 0.5), (100.02, 100.0))


def _truth(
    source: str = "recorded_hyperliquid_l2",
    *,
    received_ts_ms: int = OBSERVED_AT_MS - 1,
) -> ExecutionTruth:
    return ExecutionTruth.from_levels(
        coin="HYPE",
        bids=BIDS,
        asks=ASKS,
        received_ts_ms=received_ts_ms,
        exchange_ts_ms=OBSERVED_AT_MS - 2,
        source=source,
        data_origin="RECORDED_REAL",
    )


def test_execution_truth_received_after_decision_is_not_fresh() -> None:
    truth = _truth(received_ts_ms=OBSERVED_AT_MS + 1)

    assert truth.is_fresh(
        decision_ts_ms=OBSERVED_AT_MS,
        max_age_ms=5_000,
    ) is False
    with pytest.raises(ValueError, match="received after decision"):
        truth.age_ms(OBSERVED_AT_MS)


def test_execution_truth_zero_age_tolerance_requires_exact_causal_timestamps() -> None:
    exact = ExecutionTruth.from_levels(
        coin="HYPE",
        bids=BIDS,
        asks=ASKS,
        received_ts_ms=OBSERVED_AT_MS,
        exchange_ts_ms=OBSERVED_AT_MS,
        source="recorded:exact-decision-ms",
        data_origin="RECORDED_REAL",
    )
    future_receive = _truth(received_ts_ms=OBSERVED_AT_MS + 1)

    assert exact.age_ms(OBSERVED_AT_MS) == 0
    assert exact.is_fresh(decision_ts_ms=OBSERVED_AT_MS, max_age_ms=0)
    assert not future_receive.is_fresh(
        decision_ts_ms=OBSERVED_AT_MS, max_age_ms=0
    )


def test_execution_truth_rejects_nanosecond_epoch_as_out_of_supported_range() -> None:
    with pytest.raises(ValueError, match="supported positive epoch millisecond"):
        ExecutionTruth.from_levels(
            coin="HYPE",
            bids=BIDS,
            asks=ASKS,
            received_ts_ms=1_800_000_000_000_000_000,
            exchange_ts_ms=OBSERVED_AT_MS,
            source="recorded:ns-receipt",
            data_origin="RECORDED_REAL",
        )


def test_future_execution_book_cannot_create_a_fill_or_position_mutation() -> None:
    truth = _truth(received_ts_ms=OBSERVED_AT_MS + 1)
    market = CausalMarketSnapshot.from_truth(
        truth,
        decision_ts_ms=OBSERVED_AT_MS,
    )

    result = execute_paper_intent(_execution_intent(), market)

    assert result.execution.reason == "RECEIVED_TIMESTAMP_AFTER_DECISION"
    assert result.execution.fill_price is None
    assert result.execution.filled_notional_usdc == 0.0
    assert result.position_mutation.status == "NO_MUTATION"


def test_l2_cache_rejects_a_book_received_after_the_decision() -> None:
    from hl_observer.collection import l2_snapshot_cache

    env = {
        l2_snapshot_cache.CONSUME_FLAG: "1",
        l2_snapshot_cache.FRESH_ENV: "90",
    }
    l2_snapshot_cache.clear()
    try:
        l2_snapshot_cache.push_book(
            "HYPE",
            BIDS,
            ASKS,
            received_ts_ms=OBSERVED_AT_MS + 1,
            exchange_ts_ms=OBSERVED_AT_MS,
        )

        assert l2_snapshot_cache.live_execution_truth_for(
            "HYPE",
            decision_ts_ms=OBSERVED_AT_MS,
            env=env,
        ) is None
    finally:
        l2_snapshot_cache.clear()


def _execution_intent(*, action: str = "OPEN") -> PaperExecutionIntent:
    return PaperExecutionIntent(
        strategy_id="copy_vault",
        coin="HYPE",
        position_side="LONG",
        action=action,
        target_notional_usdc=100.0,
        confidence=0.95,
        created_at_ms=OBSERVED_AT_MS,
    )


def _strategy_intent() -> PaperIntent:
    return PaperIntent(
        strategy_id="copy_vault",
        coin="HYPE",
        side=IntentSide.LONG,
        action=IntentAction.OPEN,
        target_notional_usdt=100.0,
        confidence=0.95,
        created_at_ms=OBSERVED_AT_MS,
    )


def test_canonical_execution_is_deterministic_and_paper_only() -> None:
    intent = _execution_intent()
    market = CausalMarketSnapshot.from_truth(_truth(), decision_ts_ms=OBSERVED_AT_MS)

    first = execute_paper_intent(intent, market)
    second = execute_paper_intent(intent, market)

    assert first == second
    assert first.accepted is True
    assert first.plan.real_execution is False
    assert first.ledger_event.real_execution is False
    assert first.execution.execution_snapshot_id == market.snapshot_id
    assert first.position_mutation.action == "OPEN"
    assert first.equity_event.realized_pnl_delta_usdc is None
    assert first.equity_event.accounting_status == "PENDING_POSITION_ACCOUNTING"


def test_main_engine_connector_and_direct_core_share_fill_truth() -> None:
    direct = execute_paper_intent(
        _execution_intent(),
        CausalMarketSnapshot.from_truth(_truth(), decision_ts_ms=OBSERVED_AT_MS),
    )

    connector = PaperSimConnector()
    connector_result = connector.apply_intent(
        approve_with_risk(_strategy_intent(), lambda _: (True, ())),
        mid_price=100.0,
        top_depth_usdt=None,
        observed_at_ms=OBSERVED_AT_MS,
        bids=BIDS,
        asks=ASKS,
        exchange_ts_ms=OBSERVED_AT_MS - 2,
        min_fill_ratio=0.0,
    )
    assert connector_result.accepted is True
    assert connector_result.fill is not None

    delta = LeaderDelta(
        delta_id="ld:canonical:hype:open",
        wallet=WALLET,
        coin="HYPE",
        action=LifecycleAction.OPEN_LONG,
        previous_size=0.0,
        current_size=1.0,
        delta_size=1.0,
        observed_at_ms=OBSERVED_AT_MS,
        leader_event_time_ms=OBSERVED_AT_MS,
        source="recorded_test",
        confidence=0.95,
        evidence_ref="fill:canonical",
    )
    engine = PaperEngine(
        config=PaperEngineConfig(
            max_position_usdt=100.0,
            max_total_exposure_usdt=100.0,
            leverage=1.0,
            strict_execution_truth=True,
        )
    )
    engine_result = engine.apply_delta(
        delta,
        market_price=100.0,
        observed_at_ms=OBSERVED_AT_MS,
        edge_remaining_bps=100.0,
        spread_bps=2.0,
        estimated_slippage_bps=2.0,
        top_depth_usdt=None,
        wallet_score=100.0,
        signal_score=100.0,
        marks={"HYPE": 100.0},
        execution_truth=_truth(),
        decision_context={"strategy_id": "copy_vault"},
    )

    assert engine_result.accepted is True
    assert engine_result.trade is not None
    assert engine_result.trade.fill_price == direct.execution.fill_price
    assert connector_result.fill.fill_price == direct.execution.fill_price
    assert engine_result.trade.filled_notional_usdt == direct.execution.filled_notional_usdc
    assert connector_result.fill.notional_usdt == direct.execution.requested_notional_usdc
    assert (
        engine_result.decision_context["canonical_execution_plan_id"]
        == direct.plan.plan_id
    )
    evidence = connector_result.evidence["canonical_execution"]
    assert evidence["execution"]["fill_price"] == direct.execution.fill_price
    assert evidence["execution"]["filled_notional_usdc"] == direct.execution.filled_notional_usdc
    assert evidence["execution"]["net_cost_bps"] == direct.execution.net_cost_bps


def test_connector_refuses_observed_book_when_source_timestamp_is_missing() -> None:
    connector = PaperSimConnector()
    result = connector.apply_intent(
        approve_with_risk(_strategy_intent(), lambda _: (True, ())),
        mid_price=100.0,
        top_depth_usdt=None,
        observed_at_ms=OBSERVED_AT_MS,
        bids=BIDS,
        asks=ASKS,
        min_fill_ratio=0.0,
    )

    assert result.accepted is False
    assert result.reason_codes == ("SOURCE_TIMESTAMP_MISSING",)
    assert result.evidence["canonical_execution"]["liquidity_reservation"] is None
    assert connector.fills == ()


def test_canonical_intent_and_execution_truth_preserve_symbol_case() -> None:
    truth = ExecutionTruth.from_levels(
        coin="kPEPE",
        bids=[(0.00001, 100_000_000.0)],
        asks=[(0.00002, 100_000_000.0)],
        received_ts_ms=OBSERVED_AT_MS - 1,
        exchange_ts_ms=OBSERVED_AT_MS - 2,
        source="recorded_hyperliquid_l2",
        data_origin="RECORDED_REAL",
    )
    intent = PaperExecutionIntent(
        strategy_id="copy_vault",
        coin="kPEPE",
        position_side="LONG",
        action="OPEN",
        target_notional_usdc=100.0,
        created_at_ms=OBSERVED_AT_MS,
    )

    market = CausalMarketSnapshot.from_truth(truth, decision_ts_ms=OBSERVED_AT_MS)
    result = execute_paper_intent(intent, market)

    assert truth.coin == market.coin == intent.coin == "kPEPE"
    assert result.accepted is True


def test_canonical_execution_refuses_a_case_mismatched_instrument() -> None:
    truth = ExecutionTruth.from_levels(
        coin="kPEPE",
        bids=[(0.00001, 100_000_000.0)],
        asks=[(0.00002, 100_000_000.0)],
        received_ts_ms=OBSERVED_AT_MS - 1,
        exchange_ts_ms=OBSERVED_AT_MS - 2,
        source="recorded_hyperliquid_l2",
        data_origin="RECORDED_REAL",
    )
    intent = PaperExecutionIntent(
        strategy_id="copy_vault",
        coin="KPEPE",
        position_side="LONG",
        action="OPEN",
        target_notional_usdc=100.0,
        created_at_ms=OBSERVED_AT_MS,
    )
    market = CausalMarketSnapshot.from_truth(truth, decision_ts_ms=OBSERVED_AT_MS)

    with pytest.raises(ValueError, match="does not match"):
        execute_paper_intent(intent, market)


def test_canonical_execution_maps_close_long_to_sell() -> None:
    close_intent = _execution_intent(action="CLOSE")
    result = execute_paper_intent(
        close_intent,
        CausalMarketSnapshot.from_truth(_truth(), decision_ts_ms=OBSERVED_AT_MS),
    )

    assert result.plan.execution_side == "SELL"
    assert result.execution.fill_price is not None
    assert result.execution.fill_price < 100.0
    assert result.position_mutation.quantity_delta < 0
