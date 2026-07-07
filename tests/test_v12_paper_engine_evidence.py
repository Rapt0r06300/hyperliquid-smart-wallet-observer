from __future__ import annotations

from dataclasses import replace

from hl_observer.evidence.decision_ledger import evidence_from_paper_result
from hl_observer.paper_trading.paper_engine import PaperEngine, PaperEngineConfig
from hl_observer.position_lifecycle.reconstructor import LifecycleAction
from hl_observer.signals.leader_delta import LeaderDelta


WALLET = "0x" + "b" * 40


def _delta(action: LifecycleAction, previous: float, current: float, ts: int = 1_700_000_000_000) -> LeaderDelta:
    return LeaderDelta(
        delta_id=f"ld:test:{action.value}:{previous}:{current}:{ts}",
        wallet=WALLET,
        coin="HYPE",
        action=action,
        previous_size=previous,
        current_size=current,
        delta_size=current - previous,
        observed_at_ms=ts + 100,
        leader_event_time_ms=ts,
        source="unit_test",
        confidence=0.95,
        evidence_ref="fill:test",
    )


def _apply_ok(engine: PaperEngine, delta: LeaderDelta, price: float, observed: int = 1_700_000_000_100):
    return engine.apply_delta(
        delta,
        market_price=price,
        observed_at_ms=observed,
        edge_remaining_bps=80.0,
        spread_bps=2.0,
        estimated_slippage_bps=2.0,
        top_depth_usdt=100_000.0,
        wallet_score=90.0,
        signal_score=80.0,
        marks={"HYPE": price},
    )


def test_v12_paper_engine_opens_marks_and_closes_local_position():
    engine = PaperEngine(config=PaperEngineConfig(max_position_usdt=40.0, default_top_depth_usdt=100_000.0))

    open_result = _apply_ok(engine, _delta(LifecycleAction.OPEN_LONG, 0.0, 1.0), price=100.0)

    assert open_result.accepted
    assert open_result.trade is not None
    assert open_result.trade.action == "OPEN"
    assert open_result.trade.trade_id.startswith("papertrade:")
    assert len(engine.positions) == 1

    equity, unrealized, drawdown = engine.mark_to_market({"HYPE": 103.0})
    assert equity > 1000.0
    assert unrealized > 0
    assert drawdown == 0

    close_result = _apply_ok(
        engine,
        _delta(LifecycleAction.CLOSE_LONG, 1.0, 0.0, ts=1_700_000_010_000),
        price=104.0,
        observed=1_700_000_010_100,
    )

    assert close_result.accepted
    assert close_result.trade is not None
    assert close_result.trade.action == "CLOSE"
    assert close_result.realized_pnl_usdt > 0
    assert len(engine.positions) == 0


def test_v12_paper_engine_denies_low_edge_without_opening_position():
    engine = PaperEngine(config=PaperEngineConfig(max_position_usdt=40.0))
    delta = _delta(LifecycleAction.OPEN_SHORT, 0.0, -1.0)
    result = engine.apply_delta(
        delta,
        market_price=100.0,
        observed_at_ms=1_700_000_000_100,
        edge_remaining_bps=0.0,
        spread_bps=2.0,
        estimated_slippage_bps=2.0,
        top_depth_usdt=100_000.0,
        wallet_score=90.0,
        signal_score=80.0,
        marks={"HYPE": 100.0},
    )

    assert not result.accepted
    assert result.trade is not None
    assert result.trade.action == "NO_TRADE"
    assert len(engine.positions) == 0
    assert "edge remaining is negative" in result.reason_codes


def test_v12_paper_engine_refuses_flip_and_evidence_is_deterministic():
    engine = PaperEngine(config=PaperEngineConfig(max_position_usdt=40.0))
    flip = _delta(LifecycleAction.FLIP, 1.0, -1.0)
    flip = replace(flip, reason_codes=("FLIP_NO_DIRECT_PAPER_ENTRY",), confidence=0.2)

    result = _apply_ok(engine, flip, price=100.0)
    evidence1 = evidence_from_paper_result(flip, result)
    evidence2 = evidence_from_paper_result(flip, result)

    assert not result.accepted
    assert result.trade is not None
    assert result.trade.action == "NO_TRADE"
    assert "FLIP_NO_DIRECT_PAPER_ENTRY" in evidence1.reason_codes
    assert evidence1.evidence_hash == evidence2.evidence_hash
    assert evidence1.source_refs == ("leader_delta", "risk_engine", "paper_engine")


def test_v12_paper_engine_follows_exit_even_when_entry_edge_gate_would_block():
    engine = PaperEngine(config=PaperEngineConfig(max_position_usdt=40.0, default_top_depth_usdt=100_000.0))
    open_result = _apply_ok(engine, _delta(LifecycleAction.OPEN_SHORT, 0.0, -1.0), price=100.0)
    assert open_result.accepted
    assert len(engine.positions) == 1

    close = _delta(LifecycleAction.CLOSE_SHORT, -1.0, 0.0, ts=1_700_000_090_000)
    result = engine.apply_delta(
        close,
        market_price=97.0,
        observed_at_ms=1_700_000_090_100,
        edge_remaining_bps=0.0,
        spread_bps=999.0,
        estimated_slippage_bps=999.0,
        top_depth_usdt=1.0,
        wallet_score=0.0,
        signal_score=0.0,
        marks={"HYPE": 97.0},
    )

    assert result.accepted
    assert result.trade is not None
    assert result.trade.action == "CLOSE"
    assert result.realized_pnl_usdt > 0
    assert len(engine.positions) == 0
