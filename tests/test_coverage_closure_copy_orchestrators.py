from __future__ import annotations

from types import SimpleNamespace

import pytest

import hl_observer.copying.viral_bot_engine as viral_module
from hl_observer.copying.circuit_breaker import CircuitBreakerConfig, CircuitState
from hl_observer.copying.kelly_sizing import KellySizingConfig
from hl_observer.copying.pipeline_integrator import PipelineIntegrator
from hl_observer.copying.realtime_magic_score import RealtimeCopyRiskConfig
from hl_observer.copying.viral_bot_engine import TradeDecision, ViralBotEngine
from hl_observer.risk.advanced_risk_manager import (
    AdvancedRiskConfig,
    RiskAssessment,
    RiskVeto,
    VolatilityRegime,
)


def _signal_kwargs() -> dict:
    return {
        "signal_id": "sig-1",
        "leader_address": "0xABC",
        "coin": "BTC",
        "side": "LONG",
        "action_type": "OPEN_LONG",
        "leader_expected_edge_bps": 40.0,
        "leader_consistency_factor": 1.0,
        "signal_age_ms": 100,
        "consensus_wallets": 3,
        "liquidity_score": 0.9,
        "leader_score": 90.0,
        "leader_reference_price": 100.0,
        "current_mid": 100.0,
        "leader_notional_usdt": 100.0,
        "current_open_exposure_usdt": 0.0,
        "current_open_positions": 0,
        "max_open_positions": 5,
        "leader_win_rate": 0.65,
    }


def _score(*, accepted: bool, edge: float = 20.0):
    return SimpleNamespace(
        accepted=accepted,
        refusal_reasons=[] if accepted else ["SCORING_REFUSED"],
        edge_remaining_bps=edge,
        opportunity_score=77.0,
    )


def _kelly(*, size: float):
    return SimpleNamespace(
        position_size_usdt=size,
        warnings=() if size > 0 else ("NO_EDGE",),
        kelly_fraction_used=0.02,
    )


def _exit():
    return SimpleNamespace(
        plan_type="adaptive",
        hard_stop_bps=12.0,
        take_profit_bps=30.0,
        trailing_activation_bps=15.0,
    )


def test_viral_engine_rejects_ejected_leader_without_scoring(monkeypatch) -> None:
    engine = ViralBotEngine()
    engine.force_eject_leader("0xABC")
    called = {"score": False}

    def _never(*args, **kwargs):
        called["score"] = True
        raise AssertionError("scoring should not run for an ejected leader")

    monkeypatch.setattr(viral_module, "score_realtime_copy_candidate", _never)
    result = engine.evaluate_signal(**_signal_kwargs())
    assert not result.accepted
    assert result.decision == TradeDecision.REJECT_LEADER_EJECTED
    assert result.leader_status == "EJECTED"
    assert engine.total_rejected == 1 and engine.total_leader_ejects == 1
    assert called["score"] is False


def test_viral_engine_scoring_circuit_kelly_and_acceptance_branches(monkeypatch) -> None:
    engine = ViralBotEngine()

    monkeypatch.setattr(viral_module, "score_realtime_copy_candidate", lambda *a, **k: _score(accepted=False))
    result = engine.evaluate_signal(**_signal_kwargs())
    assert result.decision == TradeDecision.REJECT_SCORING
    assert result.reasons == ["SCORING_REFUSED"]

    monkeypatch.setattr(viral_module, "score_realtime_copy_candidate", lambda *a, **k: _score(accepted=True))

    def _paused(state, config):
        state.state = CircuitState.PAUSED
        state.reasons = ["TEST_PAUSE"]
        state.sizing_multiplier = 0.0
        return state

    monkeypatch.setattr(viral_module, "evaluate_circuit_breaker", _paused)
    result = engine.evaluate_signal(**{**_signal_kwargs(), "signal_id": "sig-2"})
    assert result.decision == TradeDecision.REJECT_CIRCUIT_BREAKER
    assert engine.total_circuit_breaker_blocks == 1

    def _normal(state, config):
        state.state = CircuitState.NORMAL
        state.reasons = []
        state.sizing_multiplier = 0.8
        return state

    monkeypatch.setattr(viral_module, "evaluate_circuit_breaker", _normal)
    monkeypatch.setattr(viral_module, "kelly_criterion_size", lambda **kwargs: _kelly(size=0.0))
    result = engine.evaluate_signal(**{**_signal_kwargs(), "signal_id": "sig-3"})
    assert result.decision == TradeDecision.REJECT_KELLY_NO_EDGE
    assert engine.total_kelly_rejects == 1

    monkeypatch.setattr(viral_module, "kelly_criterion_size", lambda **kwargs: _kelly(size=25.0))
    monkeypatch.setattr(viral_module, "select_exit_plan", lambda *args, **kwargs: _exit())
    result = engine.evaluate_signal(**{**_signal_kwargs(), "signal_id": "sig-4"})
    assert result.accepted
    assert result.decision == TradeDecision.ACCEPT_PAPER_SIMULATION
    assert result.position_size_usdt == 20.0
    assert result.exit_plan.plan_type == "adaptive"
    assert result.leader_status == "NEW"
    assert engine.total_accepted == 1
    assert engine.avg_time_to_decide_ms >= 0


def test_viral_engine_records_trade_ejects_reports_and_resets(monkeypatch) -> None:
    engine = ViralBotEngine()
    monkeypatch.setattr(viral_module, "record_trade_result", lambda state, pnl_bps, pnl_usdt: state)

    for i in range(4):
        engine.record_closed_trade(
            leader_address="0xBAD",
            coin="BTC",
            side="LONG",
            entry_price=100.0,
            exit_price=99.0,
            notional_usdt=10.0,
            pnl_usdt=-1.0,
            pnl_bps=-10.0,
            entry_timestamp=float(i),
            exit_timestamp=float(i + 1),
            signal_age_at_entry_ms=50,
        )
    assert "0xbad" in engine._ejected_leaders
    assert engine.get_active_leaders() == []

    report = engine.get_session_report()
    assert report["simulation_only"] is True
    assert report["real_orders_created"] == 0
    assert report["real_money_used"] == 0
    assert report["key_material_used"] == 0
    assert "0xbad" in report["ejected_leaders"]

    engine.reset_ejections()
    assert engine._ejected_leaders == set()
    assert engine.get_active_leaders() == ["0xbad"]
    engine.force_eject_leader("0xBAD")
    assert engine.get_active_leaders() == []


def test_pipeline_initialize_applies_configs_and_equity() -> None:
    pipeline = PipelineIntegrator()
    copy_cfg = RealtimeCopyRiskConfig()
    kelly_cfg = KellySizingConfig(starting_equity_usdt=2222.0)
    circuit_cfg = CircuitBreakerConfig(cooldown_minutes=7.0)
    risk_cfg = AdvancedRiskConfig(max_var_pct=2.0)
    pipeline.initialize(
        1500.0,
        copy_config=copy_cfg,
        kelly_config=kelly_cfg,
        circuit_config=circuit_cfg,
        risk_config=risk_cfg,
    )
    assert pipeline.engine.copy_config is copy_cfg
    assert pipeline.engine.kelly_config is kelly_cfg
    assert pipeline.engine.circuit_config is circuit_cfg
    assert pipeline.risk_manager.config is risk_cfg
    assert pipeline.risk_manager.current_equity_usdt == 1500.0
    assert pipeline.engine.circuit_state.current_equity_usdt == 1500.0

    defaulted = PipelineIntegrator()
    defaulted.initialize(1234.0)
    assert defaulted.engine.kelly_config.starting_equity_usdt == 1234.0


def test_pipeline_viral_rejection_risk_rejection_and_acceptance(monkeypatch) -> None:
    pipeline = PipelineIntegrator()
    pipeline.initialize(1000.0)

    viral_reject = SimpleNamespace(
        accepted=False,
        decision=TradeDecision.REJECT_SCORING,
        reasons=["NO_SCORE"],
        copy_score=SimpleNamespace(edge_remaining_bps=0.0),
        circuit_state=CircuitState.NORMAL,
    )
    monkeypatch.setattr(pipeline.engine, "evaluate_signal", lambda **kwargs: viral_reject)
    result = pipeline.evaluate_and_size(**_signal_kwargs())
    assert not result.accepted
    assert result.decision == TradeDecision.REJECT_SCORING.value
    assert pipeline.total_viral_rejected == 1

    accepted_signal = SimpleNamespace(
        accepted=True,
        decision=TradeDecision.ACCEPT_PAPER_SIMULATION,
        reasons=["all_gates_passed"],
        copy_score=SimpleNamespace(edge_remaining_bps=25.0, opportunity_score=88.0),
        circuit_state=CircuitState.NORMAL,
        position_size_usdt=40.0,
        exit_plan=_exit(),
        kelly_result=SimpleNamespace(kelly_fraction_used=0.03),
    )
    monkeypatch.setattr(pipeline.engine, "evaluate_signal", lambda **kwargs: accepted_signal)

    rejected_risk = RiskAssessment(
        allowed=False,
        veto=RiskVeto.VAR_LIMIT_EXCEEDED,
        reasons=["var_exceeded"],
        volatility_regime=VolatilityRegime.HIGH,
        daily_pnl_pct=-1.0,
        drawdown_pct=2.0,
    )
    monkeypatch.setattr(pipeline.risk_manager, "evaluate_risk", lambda **kwargs: rejected_risk)
    result = pipeline.evaluate_and_size(**{**_signal_kwargs(), "signal_id": "risk-reject"})
    assert not result.accepted
    assert result.decision == "REJECT_RISK_VAR_LIMIT_EXCEEDED"
    assert pipeline.total_risk_rejected == 1

    allowed_risk = RiskAssessment(
        allowed=True,
        veto=RiskVeto.NONE,
        reasons=["risk_ok"],
        sizing_multiplier=0.5,
        volatility_regime=VolatilityRegime.NORMAL,
        daily_pnl_pct=1.0,
        drawdown_pct=0.5,
    )
    monkeypatch.setattr(pipeline.risk_manager, "evaluate_risk", lambda **kwargs: allowed_risk)
    result = pipeline.evaluate_and_size(**{**_signal_kwargs(), "signal_id": "accept"})
    assert result.accepted
    assert result.position_size_usdt == 20.0
    assert result.opportunity_score == 88.0
    assert result.kelly_fraction_used == 0.03
    assert result.exit_plan_type == "adaptive"
    assert result.hard_stop_bps == 12.0
    assert result.take_profit_bps == 30.0
    assert result.trailing_activation_bps == 15.0
    assert pipeline.total_accepted == 1


def test_pipeline_default_exit_path_recording_positions_and_report(monkeypatch) -> None:
    pipeline = PipelineIntegrator()
    pipeline.initialize(1000.0)

    accepted_signal = SimpleNamespace(
        accepted=True,
        decision=TradeDecision.ACCEPT_PAPER_SIMULATION,
        reasons=[],
        copy_score=None,
        circuit_state=CircuitState.NORMAL,
        position_size_usdt=10.0,
        exit_plan=None,
        kelly_result=None,
    )
    monkeypatch.setattr(pipeline.engine, "evaluate_signal", lambda **kwargs: accepted_signal)
    monkeypatch.setattr(
        pipeline.risk_manager,
        "evaluate_risk",
        lambda **kwargs: RiskAssessment(allowed=True, sizing_multiplier=1.0),
    )
    result = pipeline.evaluate_and_size(**_signal_kwargs())
    assert result.accepted
    assert result.exit_plan_type == "default"
    assert result.hard_stop_bps == 25.0
    assert result.take_profit_bps == 35.0
    assert result.trailing_activation_bps == 18.0

    calls = {"engine": 0, "risk": 0}
    monkeypatch.setattr(pipeline.engine, "record_closed_trade", lambda **kwargs: calls.__setitem__("engine", calls["engine"] + 1))
    monkeypatch.setattr(pipeline.risk_manager, "on_position_closed", lambda **kwargs: calls.__setitem__("risk", calls["risk"] + 1))
    pipeline.record_closed_trade(
        leader_address="0xA",
        coin="BTC",
        side="LONG",
        entry_price=100.0,
        exit_price=101.0,
        notional_usdt=10.0,
        pnl_usdt=1.0,
        pnl_bps=10.0,
        entry_timestamp=1.0,
        exit_timestamp=2.0,
        signal_age_at_entry_ms=10,
    )
    assert calls == {"engine": 1, "risk": 1}

    pipeline.on_position_opened("ETH", 10.0)
    assert "ETH" in pipeline.risk_manager.open_positions_coins
    report = pipeline.get_full_report()
    assert report["simulation_only"] is True
    assert report["real_orders_created"] == 0
    assert report["pipeline_stats"]["total_evaluated"] >= 1
