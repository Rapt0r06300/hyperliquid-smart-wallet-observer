from __future__ import annotations

from types import SimpleNamespace

import pytest

import hl_observer.copying.viral_bot_engine as vbe
from hl_observer.copying.circuit_breaker import CircuitBreakerState, CircuitState
from hl_observer.copying.viral_bot_engine import TradeDecision, ViralBotEngine


def _kwargs():
    return dict(
        signal_id="sig-1",
        leader_address="0xABC",
        coin="BTC",
        side="LONG",
        action_type="OPEN",
        leader_expected_edge_bps=20.0,
        leader_consistency_factor=0.9,
        signal_age_ms=10,
        consensus_wallets=3,
        liquidity_score=0.9,
        leader_score=0.9,
        leader_reference_price=100.0,
        current_mid=100.1,
        leader_notional_usdt=100.0,
        current_open_exposure_usdt=0.0,
        current_open_positions=0,
        max_open_positions=5,
        leader_win_rate=0.6,
    )


def _score(*, accepted=True, edge=12.0, refusals=None):
    return SimpleNamespace(
        accepted=accepted,
        edge_remaining_bps=edge,
        refusal_reasons=list(refusals or []),
    )


def _kelly(size=100.0, warnings=None):
    return SimpleNamespace(
        position_size_usdt=size,
        warnings=list(warnings or []),
        kelly_fraction_used=0.1,
    )


def test_ejected_leader_is_rejected_before_scoring(monkeypatch) -> None:
    engine = ViralBotEngine()
    engine.force_eject_leader("0xabc")
    called = False

    def scoring(*args, **kwargs):
        nonlocal called
        called = True
        raise AssertionError("scoring must not run")

    monkeypatch.setattr(vbe, "score_realtime_copy_candidate", scoring)
    result = engine.evaluate_signal(**_kwargs())
    assert called is False
    assert result.decision is TradeDecision.REJECT_LEADER_EJECTED
    assert result.accepted is False
    assert result.leader_address == "0xabc"
    assert result.leader_status == "EJECTED"
    assert engine.total_signals_evaluated == 1
    assert engine.total_rejected == 1
    assert engine.total_leader_ejects == 1


def test_scoring_rejection_carries_refusal_reasons(monkeypatch) -> None:
    engine = ViralBotEngine()
    monkeypatch.setattr(
        vbe,
        "score_realtime_copy_candidate",
        lambda *a, **k: _score(accepted=False, edge=None, refusals=["STALE", "NO_EDGE"]),
    )
    result = engine.evaluate_signal(**_kwargs())
    assert result.decision is TradeDecision.REJECT_SCORING
    assert result.reasons == ["STALE", "NO_EDGE"]
    assert result.copy_score.accepted is False
    assert engine.total_rejected == 1


def test_circuit_breaker_pause_rejects_after_positive_scoring(monkeypatch) -> None:
    engine = ViralBotEngine()
    monkeypatch.setattr(vbe, "score_realtime_copy_candidate", lambda *a, **k: _score())

    def breaker(state, config):
        state.state = CircuitState.PAUSED
        state.reasons = ["PAUSE_TEST"]
        state.sizing_multiplier = 0.0
        return state

    monkeypatch.setattr(vbe, "evaluate_circuit_breaker", breaker)
    result = engine.evaluate_signal(**_kwargs())
    assert result.decision is TradeDecision.REJECT_CIRCUIT_BREAKER
    assert result.reasons == ["circuit_breaker_PAUSED", "PAUSE_TEST"]
    assert result.circuit_state is CircuitState.PAUSED
    assert engine.total_circuit_breaker_blocks == 1
    assert engine.total_rejected == 1


def test_kelly_zero_rejects_and_preserves_warning(monkeypatch) -> None:
    engine = ViralBotEngine()
    monkeypatch.setattr(vbe, "score_realtime_copy_candidate", lambda *a, **k: _score())
    monkeypatch.setattr(vbe, "evaluate_circuit_breaker", lambda state, config: state)
    monkeypatch.setattr(vbe, "kelly_criterion_size", lambda **k: _kelly(0.0, ["NO_CAPACITY"]))
    result = engine.evaluate_signal(**_kwargs())
    assert result.decision is TradeDecision.REJECT_KELLY_NO_EDGE
    assert result.reasons == ["kelly_sizing_zero", "NO_CAPACITY"]
    assert engine.total_kelly_rejects == 1
    assert engine.total_rejected == 1


def test_acceptance_applies_circuit_multiplier_exit_plan_and_leader_context(monkeypatch) -> None:
    engine = ViralBotEngine()
    engine.circuit_state.sizing_multiplier = 0.5
    monkeypatch.setattr(vbe, "score_realtime_copy_candidate", lambda *a, **k: _score(edge=14.0))
    monkeypatch.setattr(vbe, "evaluate_circuit_breaker", lambda state, config: state)
    monkeypatch.setattr(vbe, "kelly_criterion_size", lambda **k: _kelly(120.0))
    exit_plan = SimpleNamespace(plan_type="test")
    monkeypatch.setattr(vbe, "select_exit_plan", lambda *a, **k: exit_plan)

    # Give the leader measurable prior session context.
    engine.record_closed_trade(
        leader_address="0xabc",
        coin="BTC",
        side="LONG",
        entry_price=100.0,
        exit_price=101.0,
        notional_usdt=100.0,
        pnl_usdt=2.0,
        pnl_bps=20.0,
        entry_timestamp=1.0,
        exit_timestamp=2.0,
        signal_age_at_entry_ms=5,
    )
    # Restore desired sizing after record_trade_result touched only PnL counters.
    engine.circuit_state.sizing_multiplier = 0.5

    result = engine.evaluate_signal(**_kwargs())
    assert result.accepted is True
    assert result.decision is TradeDecision.ACCEPT_PAPER_SIMULATION
    assert result.reasons == ["all_gates_passed"]
    assert result.position_size_usdt == 60.0
    assert result.exit_plan is exit_plan
    assert result.leader_status == "EVALUATING"
    assert result.leader_session_pnl_usdt == 2.0
    assert result.sizing_multiplier == 0.5
    assert engine.total_accepted == 1
    assert engine.avg_time_to_decide_ms >= 0.0


def test_closed_trade_auto_ejects_and_session_controls_work(monkeypatch) -> None:
    engine = ViralBotEngine()
    # Make ejection deterministic and quick for this behavioural test.
    engine.leader_tracker.min_trades_before_eject = 1
    engine.leader_tracker.max_consecutive_losses = 1
    engine.record_closed_trade(
        leader_address="0xBAD",
        coin="ETH",
        side="SHORT",
        entry_price=100.0,
        exit_price=101.0,
        notional_usdt=100.0,
        pnl_usdt=-3.0,
        pnl_bps=-30.0,
        entry_timestamp=10.0,
        exit_timestamp=11.5,
        signal_age_at_entry_ms=25,
    )
    assert "0xbad" in engine._ejected_leaders
    perf = engine.leader_tracker.get_leader_performance("0xBAD")
    assert perf is not None
    assert perf.total_trades == 1
    assert perf.avg_hold_duration_ms == 1500.0
    assert engine.circuit_state.session_pnl_usdt == -3.0

    engine.force_eject_leader("0xMANUAL")
    assert "0xmanual" in engine._ejected_leaders
    assert engine.get_active_leaders() == []
    engine.reset_ejections()
    assert engine._ejected_leaders == set()
    assert engine.get_active_leaders() == ["0xbad"]

    report = engine.get_session_report()
    assert report["total_signals_evaluated"] == 0
    assert report["acceptance_rate"] == 0.0
    assert report["total_trades"] == 1
    assert report["simulation_only"] is True
    assert report["real_orders_created"] == 0
    assert report["real_money_used"] == 0
    assert report["key_material_used"] == 0
