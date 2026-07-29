from __future__ import annotations

import json
from hashlib import sha256

import pytest

from hl_observer.market_truth.executable_replay import (
    FillStatus,
    ReplayIntent,
    replay_executable_fill,
)
from hl_observer.market_truth.pipeline import MarketTruthPipeline
from hl_observer.market_truth.truth_chain import TruthChain
from hl_observer.market_truth.validation import evaluate_research_candidate
from hl_observer.simulation.paper_event import PaperEventType


def _book(
    *,
    event_id: str,
    at_ms: int,
    bid: float = 100.0,
    ask: float = 101.0,
    bid_sizes: tuple[float, ...] = (2.0, 3.0),
    ask_sizes: tuple[float, ...] = (2.0, 3.0),
    score: float = 95.0,
    ready: bool = True,
    coin: str = "BTC",
) -> dict:
    bids = [
        {"px": str(bid - index), "sz": str(quantity)}
        for index, quantity in enumerate(bid_sizes)
    ]
    asks = [
        {"px": str(ask + index), "sz": str(quantity)}
        for index, quantity in enumerate(ask_sizes)
    ]
    return {
        "schema_version": "hypersmart.market_event.v1",
        "event_id": event_id,
        "event_type": "L2_BOOK_SNAPSHOT",
        "source_tick_ref": "tick:" + event_id,
        "source_id": "hyperliquid_mainnet_readonly",
        "channel": "l2Book",
        "instrument": coin,
        "observable_at_ms": at_ms,
        "received_ts_ms": at_ms - 1,
        "written_ts_ms": at_ms,
        "feed_quality_score": score,
        "data_gate_ready": ready,
        "signal_eligible": ready,
        "raw_payload": {
            "channel": "l2Book",
            "data": {
                "coin": coin,
                "time": at_ms - 2,
                "levels": [bids, asks],
            },
        },
        "parsed_summary": {
            "best_bid": bid,
            "best_ask": ask,
            "feed_quality_score": score,
            "data_gate_ready": ready,
        },
    }


def _trades(*, event_id: str, at_ms: int, trades: list[dict], coin: str = "BTC") -> dict:
    return {
        "schema_version": "hypersmart.market_event.v1",
        "event_id": event_id,
        "event_type": "PUBLIC_TRADE_BATCH",
        "source_tick_ref": "tick:" + event_id,
        "source_id": "hyperliquid_mainnet_readonly",
        "channel": "trades",
        "instrument": coin,
        "observable_at_ms": at_ms,
        "received_ts_ms": at_ms - 1,
        "written_ts_ms": at_ms,
        "feed_quality_score": 95.0,
        "data_gate_ready": True,
        "signal_eligible": True,
        "raw_payload": {"channel": "trades", "data": trades},
        "parsed_summary": {"trade_count": len(trades)},
    }


def _durable_tick(event: dict) -> dict:
    raw_text = json.dumps(
        event["raw_payload"],
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return {
        "schema_version": "hypersmart.tick.v1",
        "source_id": "hyperliquid_mainnet_readonly",
        "channel": event["channel"],
        "instrument": event["instrument"],
        "event_kind": "SNAPSHOT",
        "exchange_ts_ms": event["observable_at_ms"] - 2,
        "received_ts_ms": event["observable_at_ms"] - 1,
        "written_ts_ms": event["observable_at_ms"],
        "raw_payload": raw_text,
        "raw_sha256": sha256(raw_text.encode("utf-8")).hexdigest(),
        "parsed_summary": event["parsed_summary"],
        "provenance": {"access": "read_only", "transport": "websocket"},
    }


def test_taker_fill_uses_first_book_after_signal_plus_latency() -> None:
    events = [
        _book(event_id="before", at_ms=1_000, bid=99, ask=100),
        _book(event_id="too_early", at_ms=1_200, bid=100, ask=101),
        _book(event_id="causal", at_ms=1_260, bid=101, ask=102),
    ]
    fill = replay_executable_fill(
        ReplayIntent(
            signal_id="sig-1",
            coin="BTC",
            position_side="LONG",
            action="OPEN",
            signal_observable_at_ms=1_000,
            requested_notional_usdc=102.0,
            latency_ms=250,
        ),
        events,
    )
    assert fill.status == FillStatus.FILLED
    assert fill.source_event_id == "causal"
    assert fill.fill_price == pytest.approx(102.0)
    assert fill.observed_latency_ms == 260
    assert fill.costs.fee_usdc == pytest.approx(102.0 * 4.5 / 10_000)


def test_facade_unique_impose_canonicalisation_avant_le_fill() -> None:
    pipeline = MarketTruthPipeline()
    intent = ReplayIntent(
        signal_id="sig-pipeline",
        coin="BTC",
        position_side="LONG",
        action="OPEN",
        signal_observable_at_ms=1_000,
        requested_notional_usdc=102.0,
        latency_ms=250,
    )
    result = pipeline.run(
        intent=intent,
        durable_tick_records=[
            _durable_tick(_book(event_id="causal", at_ms=1_260, bid=101, ask=102))
        ],
    )

    assert result.applied is True
    assert result.input_tick_count == 1
    assert result.canonical_event_count == 1
    assert result.truth.fill.source_tick_ref is not None
    assert result.truth.evidence.reconciliation["ok"] is True


def test_facade_unique_conserve_un_refus_quality_dans_le_ledger() -> None:
    pipeline = MarketTruthPipeline()
    intent = ReplayIntent(
        signal_id="sig-quality-refused",
        coin="BTC",
        position_side="LONG",
        action="OPEN",
        signal_observable_at_ms=1_000,
        requested_notional_usdc=100.0,
        latency_ms=0,
    )
    bad_book = _book(event_id="unsynced", at_ms=1_001, ready=False)
    result = pipeline.run(
        intent=intent,
        durable_tick_records=[_durable_tick(bad_book)],
    )

    assert result.applied is False
    assert result.canonical_event_count == 0
    assert "DATA_QUALITY_GATE_NOT_READY" in result.rejected_tick_reasons
    assert result.truth.evidence.reason == "DATA_QUALITY_GATE_NOT_READY"
    assert result.truth.paper_events[0].event_type is PaperEventType.NO_TRADE


def test_visible_depth_produces_partial_fill_without_extrapolation() -> None:
    fill = replay_executable_fill(
        ReplayIntent(
            signal_id="sig-partial",
            coin="BTC",
            position_side="LONG",
            action="OPEN",
            signal_observable_at_ms=1_000,
            requested_quantity=10.0,
            latency_ms=0,
        ),
        [
            _book(
                event_id="thin",
                at_ms=1_000,
                bid_sizes=(1.0,),
                ask_sizes=(1.0,),
            )
        ],
    )
    assert fill.status == FillStatus.PARTIAL
    assert fill.filled_quantity == pytest.approx(1.0)
    assert fill.fill_ratio == pytest.approx(0.1)


def test_quality_gate_and_stale_book_block_execution() -> None:
    blocked = replay_executable_fill(
        ReplayIntent(
            signal_id="sig-quality",
            coin="BTC",
            position_side="SHORT",
            action="OPEN",
            signal_observable_at_ms=1_000,
            requested_notional_usdc=100,
            latency_ms=0,
        ),
        [_book(event_id="bad", at_ms=1_000, ready=False, score=20)],
    )
    assert blocked.status == FillStatus.QUALITY_BLOCKED

    stale = replay_executable_fill(
        ReplayIntent(
            signal_id="sig-stale",
            coin="BTC",
            position_side="SHORT",
            action="OPEN",
            signal_observable_at_ms=1_000,
            requested_notional_usdc=100,
            latency_ms=0,
            max_book_wait_ms=500,
        ),
        [_book(event_id="late", at_ms=2_000)],
    )
    assert stale.status == FillStatus.STALE_BOOK


def test_maker_queue_only_advances_on_matching_public_trades() -> None:
    events = [
        _book(
            event_id="queue",
            at_ms=1_000,
            bid=100.0,
            ask=101.0,
            bid_sizes=(2.0,),
        ),
        _trades(
            event_id="wrong-side",
            at_ms=1_100,
            trades=[{"coin": "BTC", "side": "B", "px": "101", "sz": "20"}],
        ),
        _trades(
            event_id="queue-only",
            at_ms=1_200,
            trades=[{"coin": "BTC", "side": "A", "px": "100", "sz": "2"}],
        ),
        _trades(
            event_id="our-fill",
            at_ms=1_300,
            trades=[{"coin": "BTC", "side": "A", "px": "100", "sz": "1"}],
        ),
    ]
    fill = replay_executable_fill(
        ReplayIntent(
            signal_id="maker",
            coin="BTC",
            position_side="LONG",
            action="OPEN",
            signal_observable_at_ms=1_000,
            requested_quantity=1.0,
            latency_ms=0,
            execution_style="MAKER",
            limit_price=100.0,
        ),
        events,
    )
    assert fill.status == FillStatus.FILLED
    assert fill.queue_ahead_quantity == pytest.approx(2.0)
    assert fill.matched_trade_quantity == pytest.approx(3.0)
    assert fill.fill_price == pytest.approx(100.0)


def test_latency_and_adverse_selection_are_measured_not_double_charged() -> None:
    events = [
        _book(event_id="signal-book", at_ms=1_000, bid=100, ask=101),
        _book(event_id="fill-book", at_ms=1_250, bid=99, ask=100),
        _book(event_id="future", at_ms=6_250, bid=97, ask=98),
    ]
    fill = replay_executable_fill(
        ReplayIntent(
            signal_id="diagnostics",
            coin="BTC",
            position_side="LONG",
            action="OPEN",
            signal_observable_at_ms=1_000,
            requested_notional_usdc=100,
            latency_ms=250,
            adverse_selection_horizon_ms=5_000,
        ),
        events,
    )
    assert fill.status == FillStatus.FILLED
    assert fill.costs.latency_cost_bps is not None
    assert fill.costs.latency_cost_bps > 0
    assert fill.costs.markout_bps is not None
    assert fill.costs.markout_bps < 0
    assert fill.costs.adverse_selection_bps == pytest.approx(-fill.costs.markout_bps)
    assert fill.costs.cash_charged_separately_usdc == fill.costs.fee_usdc


def test_truth_chain_open_add_reduce_close_and_reconcile(tmp_path) -> None:
    evidence_path = tmp_path / "evidence.jsonl"
    chain = TruthChain(evidence_path=evidence_path)

    opened = chain.execute(
        ReplayIntent(
            signal_id="open",
            coin="BTC",
            position_side="LONG",
            action="OPEN",
            signal_observable_at_ms=1_000,
            requested_notional_usdc=100,
            latency_ms=0,
        ),
        [_book(event_id="open-book", at_ms=1_000, bid=100, ask=101)],
    )
    assert opened.applied
    assert any(
        event.event_type == PaperEventType.POSITION_OPENED
        for event in opened.paper_events
    )

    added = chain.execute(
        ReplayIntent(
            signal_id="add",
            coin="BTC",
            position_side="LONG",
            action="ADD",
            signal_observable_at_ms=2_000,
            requested_notional_usdc=50,
            latency_ms=0,
        ),
        [_book(event_id="add-book", at_ms=2_000, bid=101, ask=102)],
    )
    assert added.applied
    assert any(
        event.event_type == PaperEventType.POSITION_INCREASED
        for event in added.paper_events
    )

    quantity_before = chain.ledger.positions["BTC:LONG"].quantity
    reduced = chain.execute(
        ReplayIntent(
            signal_id="reduce",
            coin="BTC",
            position_side="LONG",
            action="REDUCE",
            signal_observable_at_ms=3_000,
            requested_quantity=quantity_before / 2,
            latency_ms=0,
        ),
        [_book(event_id="reduce-book", at_ms=3_000, bid=103, ask=104)],
    )
    assert reduced.applied
    assert any(
        event.event_type == PaperEventType.POSITION_REDUCED
        for event in reduced.paper_events
    )

    closed = chain.execute(
        ReplayIntent(
            signal_id="close",
            coin="BTC",
            position_side="LONG",
            action="CLOSE",
            signal_observable_at_ms=4_000,
            latency_ms=0,
        ),
        [_book(event_id="close-book", at_ms=4_000, bid=104, ask=105)],
    )
    assert closed.applied
    assert "BTC:LONG" not in chain.ledger.positions
    assert chain.ledger.reconciliation().ok
    lines = evidence_path.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 4
    assert all(json.loads(line)["real_execution"] is False for line in lines)


def test_close_without_position_is_an_explicit_no_trade() -> None:
    chain = TruthChain()
    result = chain.execute(
        ReplayIntent(
            signal_id="orphan-close",
            coin="BTC",
            position_side="LONG",
            action="CLOSE",
            signal_observable_at_ms=1_000,
            latency_ms=0,
            requested_quantity=1.0,
        ),
        [_book(event_id="book", at_ms=1_000)],
    )
    assert not result.applied
    assert result.evidence.reason == "NO_MATCHING_PAPER_POSITION_FOR_CLOSE"
    assert result.paper_events[0].event_type == PaperEventType.NO_TRADE


def test_research_verdict_requires_oos_then_forward_paper() -> None:
    backtest = [value for _ in range(12) for value in (1.0, -0.2, 0.8, -0.1)]
    waiting = evaluate_research_candidate(
        backtest_trades=backtest,
        forward_trades=[1.0, -0.2],
        min_forward_trades=10,
    )
    assert waiting.verdict == "FORWARD_PAPER"

    accepted = evaluate_research_candidate(
        backtest_trades=backtest,
        forward_trades=[value for _ in range(6) for value in (1.0, -0.2)],
        min_forward_trades=10,
    )
    assert accepted.verdict == "PEPITE"
    assert accepted.as_dict()["profit_guaranteed"] is False

    killed = evaluate_research_candidate(
        backtest_trades=backtest,
        forward_trades=[1.0] * 12,
        evidence=[
            {
                "fill": {"status": "FILLED", "feed_quality_score": 95},
                "reconciliation": {"ok": False},
            }
        ],
    )
    assert killed.verdict == "KILL"
