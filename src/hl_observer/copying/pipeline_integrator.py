"""Pipeline Integrator — bridges ViralBotEngine + AdvancedRiskManager into the paper trading loop.

This module provides the glue layer so that routes.py can call a single
`evaluate_and_size()` method instead of calling score_realtime_copy_candidate
directly.  It replaces the old opportunity_metrics() -> simulated_notional_usdt
path with:

  1. ViralBotEngine.evaluate_signal() -> 6-gate pipeline (leader ejection,
     scoring, circuit breaker, Kelly sizing, exit plan, acceptance)
  2. AdvancedRiskManager.evaluate_risk() -> portfolio-level risk checks
     (daily loss, drawdown, VaR, category caps, vol regime, alpha decay)
  3. Combined sizing: Kelly size x circuit_breaker_mult x vol_regime_mult

SAFETY: simulation paper uniquement. Aucun ordre reel, aucun argent reel.
READ-ONLY, PAPER-ONLY, TESTNET-FIRST, DENY-BY-DEFAULT.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any

from hl_observer.copying.circuit_breaker import CircuitBreakerConfig
from hl_observer.copying.kelly_sizing import KellySizingConfig
from hl_observer.copying.realtime_magic_score import RealtimeCopyRiskConfig
from hl_observer.copying.viral_bot_engine import (
    TradeDecision,
    ViralBotEngine,
    ViralBotSignal,
)
from hl_observer.risk.advanced_risk_manager import (
    AdvancedRiskConfig,
    AdvancedRiskManager,
    RiskAssessment,
    RiskVeto,
)


@dataclass
class PipelineResult:
    """Full result of the integrated pipeline evaluation."""
    accepted: bool = False
    decision: str = "REJECT"
    reasons: list[str] = field(default_factory=list)
    position_size_usdt: float = 0.0
    viral_signal: ViralBotSignal | None = None
    risk_assessment: RiskAssessment | None = None
    edge_remaining_bps: float = 0.0
    opportunity_score: float = 0.0
    kelly_fraction_used: float = 0.0
    circuit_state: str = "NORMAL"
    volatility_regime: str = "normal"
    daily_pnl_pct: float = 0.0
    drawdown_pct: float = 0.0
    exit_plan_type: str = "default"
    hard_stop_bps: float = 25.0
    take_profit_bps: float = 35.0
    trailing_activation_bps: float = 18.0
    total_pipeline_ms: int = 0


@dataclass
class PipelineIntegrator:
    """Integrates ViralBotEngine + AdvancedRiskManager into one call.

    PAPER SIMULATION ONLY. No real orders ever.
    """
    engine: ViralBotEngine = field(default_factory=ViralBotEngine)
    risk_manager: AdvancedRiskManager = field(default_factory=AdvancedRiskManager)
    total_evaluated: int = 0
    total_accepted: int = 0
    total_viral_rejected: int = 0
    total_risk_rejected: int = 0

    def initialize(
        self,
        starting_equity: float,
        *,
        copy_config: RealtimeCopyRiskConfig | None = None,
        kelly_config: KellySizingConfig | None = None,
        circuit_config: CircuitBreakerConfig | None = None,
        risk_config: AdvancedRiskConfig | None = None,
    ) -> None:
        """Initialize the pipeline with configs."""
        if copy_config:
            self.engine.copy_config = copy_config
        if kelly_config:
            self.engine.kelly_config = kelly_config
        if circuit_config:
            self.engine.circuit_config = circuit_config
        if risk_config:
            self.risk_manager.config = risk_config
        self.risk_manager.initialize(starting_equity)
        if not kelly_config:
            self.engine.kelly_config = KellySizingConfig(
                starting_equity_usdt=starting_equity,
            )
        self.engine.circuit_state.current_equity_usdt = starting_equity
        self.engine.circuit_state.peak_equity_usdt = starting_equity

    def evaluate_and_size(
        self,
        *,
        signal_id: str,
        leader_address: str,
        coin: str,
        side: str,
        action_type: str,
        leader_expected_edge_bps: float | None,
        leader_consistency_factor: float,
        signal_age_ms: int,
        consensus_wallets: int,
        liquidity_score: float,
        leader_score: float,
        leader_reference_price: float,
        current_mid: float | None,
        leader_notional_usdt: float,
        current_open_exposure_usdt: float,
        current_open_positions: int,
        max_open_positions: int,
        leader_win_rate: float | None = None,
        category: str = "perpetual",
        current_position_notionals: list[float] | None = None,
    ) -> PipelineResult:
        """Full evaluation: ViralBotEngine gates -> AdvancedRisk gates -> final sizing."""
        start_ms = int(time.time() * 1000)
        self.total_evaluated += 1

        viral_signal = self.engine.evaluate_signal(
            signal_id=signal_id,
            leader_address=leader_address,
            coin=coin,
            side=side,
            action_type=action_type,
            leader_expected_edge_bps=leader_expected_edge_bps,
            leader_consistency_factor=leader_consistency_factor,
            signal_age_ms=signal_age_ms,
            consensus_wallets=consensus_wallets,
            liquidity_score=liquidity_score,
            leader_score=leader_score,
            leader_reference_price=leader_reference_price,
            current_mid=current_mid,
            leader_notional_usdt=leader_notional_usdt,
            current_open_exposure_usdt=current_open_exposure_usdt,
            current_open_positions=current_open_positions,
            max_open_positions=max_open_positions,
            leader_win_rate=leader_win_rate,
        )

        if not viral_signal.accepted:
            self.total_viral_rejected += 1
            end_ms = int(time.time() * 1000)
            return PipelineResult(
                accepted=False,
                decision=viral_signal.decision.value,
                reasons=viral_signal.reasons,
                viral_signal=viral_signal,
                edge_remaining_bps=(
                    viral_signal.copy_score.edge_remaining_bps
                    if viral_signal.copy_score and viral_signal.copy_score.edge_remaining_bps
                    else 0.0
                ),
                circuit_state=viral_signal.circuit_state.value,
                total_pipeline_ms=end_ms - start_ms,
            )

        risk_assessment = self.risk_manager.evaluate_risk(
            coin=coin,
            proposed_notional_usdt=viral_signal.position_size_usdt,
            category=category,
            current_open_notionals=current_position_notionals,
            signal_id=signal_id,
        )

        if not risk_assessment.allowed:
            self.total_risk_rejected += 1
            end_ms = int(time.time() * 1000)
            return PipelineResult(
                accepted=False,
                decision=f"REJECT_RISK_{risk_assessment.veto.value.upper()}",
                reasons=[*viral_signal.reasons, *risk_assessment.reasons],
                viral_signal=viral_signal,
                risk_assessment=risk_assessment,
                edge_remaining_bps=(
                    viral_signal.copy_score.edge_remaining_bps
                    if viral_signal.copy_score and viral_signal.copy_score.edge_remaining_bps
                    else 0.0
                ),
                circuit_state=viral_signal.circuit_state.value,
                volatility_regime=risk_assessment.volatility_regime.value,
                daily_pnl_pct=risk_assessment.daily_pnl_pct,
                drawdown_pct=risk_assessment.drawdown_pct,
                total_pipeline_ms=end_ms - start_ms,
            )

        final_size = (
            viral_signal.position_size_usdt
            * risk_assessment.sizing_multiplier
        )
        final_size = round(max(0.0, final_size), 2)

        exit_plan = viral_signal.exit_plan
        exit_type = "default"
        hard_stop = 25.0
        take_profit = 35.0
        trailing_act = 18.0
        if exit_plan:
            exit_type = exit_plan.plan_type
            hard_stop = exit_plan.hard_stop_bps
            take_profit = exit_plan.take_profit_bps
            trailing_act = exit_plan.trailing_activation_bps

        self.total_accepted += 1
        end_ms = int(time.time() * 1000)

        return PipelineResult(
            accepted=True,
            decision=TradeDecision.ACCEPT_PAPER_SIMULATION.value,
            reasons=[*viral_signal.reasons, *risk_assessment.reasons],
            position_size_usdt=final_size,
            viral_signal=viral_signal,
            risk_assessment=risk_assessment,
            edge_remaining_bps=(
                viral_signal.copy_score.edge_remaining_bps
                if viral_signal.copy_score and viral_signal.copy_score.edge_remaining_bps
                else 0.0
            ),
            opportunity_score=(
                viral_signal.copy_score.opportunity_score
                if viral_signal.copy_score
                else 0.0
            ),
            kelly_fraction_used=(
                viral_signal.kelly_result.kelly_fraction_used
                if viral_signal.kelly_result
                else 0.0
            ),
            circuit_state=viral_signal.circuit_state.value,
            volatility_regime=risk_assessment.volatility_regime.value,
            daily_pnl_pct=risk_assessment.daily_pnl_pct,
            drawdown_pct=risk_assessment.drawdown_pct,
            exit_plan_type=exit_type,
            hard_stop_bps=hard_stop,
            take_profit_bps=take_profit,
            trailing_activation_bps=trailing_act,
            total_pipeline_ms=end_ms - start_ms,
        )

    def record_closed_trade(
        self,
        *,
        leader_address: str,
        coin: str,
        side: str,
        entry_price: float,
        exit_price: float,
        notional_usdt: float,
        pnl_usdt: float,
        pnl_bps: float,
        entry_timestamp: float,
        exit_timestamp: float,
        signal_age_at_entry_ms: int,
        category: str = "perpetual",
    ) -> None:
        """Record a closed paper trade in both ViralBotEngine and AdvancedRiskManager."""
        self.engine.record_closed_trade(
            leader_address=leader_address,
            coin=coin,
            side=side,
            entry_price=entry_price,
            exit_price=exit_price,
            notional_usdt=notional_usdt,
            pnl_usdt=pnl_usdt,
            pnl_bps=pnl_bps,
            entry_timestamp=entry_timestamp,
            exit_timestamp=exit_timestamp,
            signal_age_at_entry_ms=signal_age_at_entry_ms,
        )
        self.risk_manager.on_position_closed(
            coin=coin,
            notional=notional_usdt,
            pnl_usdt=pnl_usdt,
            category=category,
        )

    def on_position_opened(self, coin: str, notional: float, category: str = "perpetual") -> None:
        """Track position opening in risk manager."""
        self.risk_manager.on_position_opened(coin, notional, category)

    def get_full_report(self) -> dict:
        """Combined report from both engines."""
        engine_report = self.engine.get_session_report()
        risk_report = self.risk_manager.get_risk_report()
        return {
            "pipeline_stats": {
                "total_evaluated": self.total_evaluated,
                "total_accepted": self.total_accepted,
                "total_viral_rejected": self.total_viral_rejected,
                "total_risk_rejected": self.total_risk_rejected,
                "acceptance_rate": (
                    self.total_accepted / max(1, self.total_evaluated)
                ),
            },
            "viral_engine": engine_report,
            "advanced_risk": risk_report,
            "simulation_only": True,
            "real_orders_created": 0,
            "real_money_used": 0,
            "key_material_used": 0,
        }
