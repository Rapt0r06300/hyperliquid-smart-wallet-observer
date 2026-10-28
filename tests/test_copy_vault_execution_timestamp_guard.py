from __future__ import annotations

import json

import pytest

from hl_observer.collection import l2_snapshot_cache
from hl_observer.copy_wallet.copy_conflict_resolver import LeaderVote
from hl_observer.paper_trading.canonical_execution import (
    CausalMarketSnapshot,
    PaperExecutionIntent,
    execute_paper_intent,
)
from hl_observer.paper_trading.exec_model import simulate_execution
from hl_observer.paper_trading.execution_truth import ExecutionTruth
from hl_observer.paper_trading.liquidity_consumption import LiquidityConsumptionLedger
from hl_observer.paper_trading.paper_engine import PaperEngine, PaperEngineConfig
from hl_observer.position_lifecycle.reconstructor import LifecycleAction
from hl_observer.signals.leader_delta import LeaderDelta

DECISION_MS = 1_800_000_000_000
BIDS = ((99.99, 100.0),)
ASKS = ((100.01, 100.0),)


def _truth(*, source_time=DECISION_MS - 2, receive_time=DECISION_MS - 1):
    return ExecutionTruth.from_levels(
        coin="HYPE",
        bids=BIDS,
        asks=ASKS,
        received_ts_ms=receive_time,
        exchange_ts_ms=source_time,
        source="recorded_hyperliquid_l2",
        data_origin="RECORDED_REAL",
    )


def _intent():
    return PaperExecutionIntent(
        strategy_id="copy_vault",
        coin="HYPE",
        position_side="LONG",
        action="OPEN",
        target_notional_usdc=50.0,
        created_at_ms=DECISION_MS,
    )


@pytest.mark.parametrize(
    ("source_time", "receive_time", "expected_reason"),
    [
        (None, DECISION_MS - 1, "SOURCE_TIMESTAMP_MISSING"),
        ("not-an-integer", DECISION_MS - 1, "SOURCE_TIMESTAMP_INVALID"),
        (0, DECISION_MS - 1, "SOURCE_TIMESTAMP_INVALID"),
        (True, DECISION_MS - 1, "SOURCE_TIMESTAMP_INVALID"),
        (DECISION_MS - 2.0, DECISION_MS - 1, "SOURCE_TIMESTAMP_INVALID"),
        (DECISION_MS + 1, DECISION_MS - 1, "SOURCE_TIMESTAMP_AFTER_DECISION"),
        (DECISION_MS - 1, DECISION_MS - 2, "SOURCE_TIMESTAMP_AFTER_RECEIPT"),
        (DECISION_MS - 2, DECISION_MS + 1, "RECEIVED_TIMESTAMP_AFTER_DECISION"),
    ],
)
def test_invalid_causal_book_timestamp_cannot_fill_or_consume_ledger(
    source_time, receive_time, expected_reason
):
    truth = _truth(source_time=source_time, receive_time=receive_time)
    ledger = LiquidityConsumptionLedger()

    result = execute_paper_intent(
        _intent(),
        CausalMarketSnapshot.from_truth(truth, decision_ts_ms=DECISION_MS),
        liquidity_ledger=ledger,
    )

    assert result.execution.reason == expected_reason
    assert result.execution.cost_status == "UNMEASURABLE"
    assert result.execution.fill_price is None
    assert result.execution.filled_notional_usdc == 0.0
    assert result.position_mutation.status == "NO_MUTATION"
    assert result.equity_event.filled_notional_usdc == 0.0
    assert result.liquidity_reservation is None
    assert ledger.snapshot() == ()
    assert ledger._outcomes == {}


def test_future_execution_truth_is_rejected_by_exec_model_without_fill():
    truth = _truth(receive_time=DECISION_MS + 1)

    result = simulate_execution(
        side="BUY",
        notional_usdc=50.0,
        mid_price=100.0,
        execution_truth=truth,
        decision_ts_ms=DECISION_MS,
        strict_book=True,
    )

    assert result.reason == "RECEIVED_TIMESTAMP_AFTER_DECISION"
    assert result.cost_status == "UNMEASURABLE"
    assert result.fill_price is None
    assert result.filled_notional_usdc == 0.0
    assert result.missed_notional_usdc == 50.0


def test_older_source_timestamp_with_ordered_receipt_is_valid():
    truth = _truth(source_time=DECISION_MS - 100, receive_time=DECISION_MS - 1)

    result = execute_paper_intent(
        _intent(),
        CausalMarketSnapshot.from_truth(truth, decision_ts_ms=DECISION_MS),
    )

    assert result.accepted is True
    assert truth.exchange_ts_raw == DECISION_MS - 100
    assert truth.exchange_ts_status == "VALID"


def test_source_timestamp_stale_even_when_local_receipt_is_recent():
    truth = _truth(source_time=DECISION_MS - 5_001, receive_time=DECISION_MS - 1)

    result = execute_paper_intent(
        _intent(),
        CausalMarketSnapshot.from_truth(truth, decision_ts_ms=DECISION_MS),
        max_book_age_ms=5_000,
    )

    assert result.execution.reason == "STALE_SOURCE_TIMESTAMP"
    assert result.execution.cost_status == "UNMEASURABLE"
    assert result.execution.filled_notional_usdc == 0.0


def test_l2_poller_preserves_invalid_time_and_does_not_publish_derived_costs(monkeypatch):
    l2_snapshot_cache.clear()
    env = {l2_snapshot_cache.CONSUME_FLAG: "1"}
    payload = {
        "time": "not-an-integer",
        "levels": [
            [{"px": "99.99", "sz": "100"}],
            [{"px": "100.01", "sz": "100"}],
        ],
    }
    monkeypatch.setattr(l2_snapshot_cache.time, "time", lambda: DECISION_MS / 1000)

    try:
        count = l2_snapshot_cache.poll_once(
            ["HYPE"],
            opener=lambda url, body, timeout: json.dumps(payload).encode(),
            env=env,
        )
        truth = l2_snapshot_cache._book_cache["HYPE"]

        assert count == 1
        assert truth.exchange_ts_ms is None
        assert truth.exchange_ts_raw == "not-an-integer"
        assert truth.exchange_ts_status == "INVALID"
        assert l2_snapshot_cache.live_costs_for("HYPE", env=env) is None
        assert l2_snapshot_cache.live_execution_truth_for("HYPE", decision_ts_ms=DECISION_MS, env=env) is None
        assert (
            l2_snapshot_cache.live_execution_truth_refusal_for("HYPE", decision_ts_ms=DECISION_MS, env=env)
            == "SOURCE_TIMESTAMP_INVALID"
        )
    finally:
        l2_snapshot_cache.clear()


def test_paper_engine_timestamp_refusal_does_not_mutate_ledger_or_equity():
    truth = _truth(source_time=None)
    engine = PaperEngine(config=PaperEngineConfig(strict_execution_truth=True))
    before = engine.ledger.snapshot()
    events_before = tuple(engine.ledger.events)
    cash_before = engine.cash_usdt
    realized_before = engine.realized_pnl_usdt
    delta = LeaderDelta(
        delta_id="timestamp-guard-open",
        wallet="0x" + "a" * 40,
        coin="HYPE",
        action=LifecycleAction.OPEN_LONG,
        previous_size=0.0,
        current_size=1.0,
        delta_size=1.0,
        observed_at_ms=DECISION_MS,
        leader_event_time_ms=DECISION_MS - 1,
        source="recorded_test",
        confidence=0.95,
        evidence_ref="fill:timestamp-guard",
    )

    result = engine.apply_delta(
        delta,
        market_price=100.0,
        observed_at_ms=DECISION_MS,
        edge_remaining_bps=100.0,
        spread_bps=2.0,
        estimated_slippage_bps=2.0,
        top_depth_usdt=None,
        wallet_score=100.0,
        signal_score=100.0,
        marks={"HYPE": 100.0},
        execution_truth=truth,
        decision_context={"strategy_id": "copy_vault"},
    )

    assert result.accepted is False
    assert result.reason_codes == ("SOURCE_TIMESTAMP_MISSING",)
    assert result.trade is not None and result.trade.fill_price is None
    assert result.ledger_snapshot == before
    assert tuple(engine.ledger.events) == events_before
    assert engine.positions == ()
    assert engine.cash_usdt == cash_before
    assert engine.realized_pnl_usdt == realized_before


def test_copy_vote_adapter_reports_timestamp_refusal_without_paper_fill(monkeypatch):
    from hl_observer.paper_trading import fusion_paper_engine_adapter as adapter

    monkeypatch.setenv("HYPERSMART_V26_LIVE_BOOK_COSTS", "1")
    monkeypatch.setenv("HYPERSMART_REQUIRE_EMPIRICAL_EDGE", "0")
    l2_snapshot_cache.clear()
    l2_snapshot_cache.push_book(
        "HYPE",
        BIDS,
        ASKS,
        received_ts_ms=DECISION_MS - 1,
        exchange_ts_ms=None,
    )

    try:
        result = adapter.run_copy_votes_through_paper_engine(
            (
                LeaderVote(wallet="0x1", coin="HYPE", side="LONG", score=2.0, observed_at_ms=DECISION_MS - 1),
                LeaderVote(wallet="0x2", coin="HYPE", side="LONG", score=1.0, observed_at_ms=DECISION_MS - 1),
            ),
            market_price=100.0,
            observed_at_ms=DECISION_MS,
        )

        assert result.accepted_count == 0
        assert result.decisions == ()
        assert result.refusal_reasons == ("SOURCE_TIMESTAMP_MISSING",)
        assert result.equity_usdt == 200.0
    finally:
        l2_snapshot_cache.clear()


def test_copy_vote_adapter_surfaces_invalid_l2_freshness_config(monkeypatch):
    from hl_observer.paper_trading import fusion_paper_engine_adapter as adapter

    monkeypatch.setenv("HYPERSMART_V26_LIVE_BOOK_COSTS", "1")
    monkeypatch.setenv("HYPERSMART_REQUIRE_EMPIRICAL_EDGE", "0")
    monkeypatch.setenv("HYPERSMART_V26_BOOK_FRESH_S", "nan")
    l2_snapshot_cache.clear()
    l2_snapshot_cache.push_book(
        "HYPE",
        BIDS,
        ASKS,
        received_ts_ms=DECISION_MS - 1,
        exchange_ts_ms=DECISION_MS - 2,
    )

    try:
        result = adapter.run_copy_votes_through_paper_engine(
            (
                LeaderVote(wallet="0x1", coin="HYPE", side="LONG", score=2.0, observed_at_ms=DECISION_MS - 1),
                LeaderVote(wallet="0x2", coin="HYPE", side="LONG", score=1.0, observed_at_ms=DECISION_MS - 1),
            ),
            market_price=100.0,
            observed_at_ms=DECISION_MS,
        )

        assert result.accepted_count == 0
        assert result.decisions == ()
        assert result.refusal_reasons == ("INVALID_L2_FRESHNESS_CONFIG",)
        assert result.equity_usdt == 200.0
    finally:
        l2_snapshot_cache.clear()
