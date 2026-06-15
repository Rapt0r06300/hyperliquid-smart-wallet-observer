"""Viral Bot Engine — orchestrator integrating all copy-trading improvements.

This module reproduces the architecture of the viral Claude/Polymarket bots
adapted for dYdX v4 perpetual futures in SIMULATION ONLY mode.

Architecture (inspired by LearnWithMeAI's 3-Job pattern):

  Job A — Leader Discovery (periodic, e.g. every 6 hours)
    Leaderboard scan → wallet scoring (with viral hard gates) → shortlist

  Job B — Signal Detection (continuous, every 6s cycle)
    Position delta monitoring → signal detection → edge calculation →
    circuit breaker check → Kelly sizing → paper trade simulation

  Job C — Performance Reporting (periodic, e.g. every 30 min)
    Per-leader PnL attribution → leader rotation → session summary

Key improvements from viral bot research:
  1. Kelly Criterion sizing (from Polyphemus)
  2. Circuit breaker with drawdown/streak limits (from ClaudePolymarketTrader)
  3. Per-leader PnL tracking and auto-rotation (from LearnWithMeAI)
  4. Enhanced exit system with breakeven/time stops (from ClaudePolymarketTrader)
  5. Stricter wallet scoring hard gates (from QuickNode/QuantVPS)
  6. Time-to-copy tracking for latency measurement
  7. Adaptive position sizing based on signal quality

SAFETY: simulation paper uniquement. Aucun ordre réel, aucun argent réel,
aucune clé privée, aucun seed, aucune mnemonic, aucune signature,
aucun dépôt/retrait, aucun wallet connect, aucun appel d'API privée
pour trader. READ-ONLY, PAPER-ONLY, TESTNET-FIRST, DENY-BY-DEFAULT.
Un signal n'est jamais un ordre. Un paper trade n'est jamais un ordre.
Si une donnée est incertaine, trop vieille ou incomplète: NO_TRADE.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
try:
    from enum import StrEnum
except ImportError:
    from enum import Enum
    class StrEnum(str, Enum): pass

from hl_observer.copying.circuit_breaker import (
    CircuitBreakerConfig,
    CircuitBreakerState,
    CircuitState,
    evaluate_circuit_breaker,
    record_trade_result,
)
from hl_observer.copying.kelly_sizing import (
    KellySizingConfig,
    KellySizingResult,
    kelly_criterion_size,
)
from hl_observer.copying.leader_pnl_tracker import (
    LeaderPnLTracker,
    LeaderTradeRecord,
)
from hl_observer.copying.realtime_magic_score import (
    RealtimeCopyRiskConfig,
    RealtimeCopyScore,
    RealtimeCopyScoreInput,
    clamp,
    score_realtime_copy_candidate,
)
from hl_observer.exits.exit_engine import (
    ExitPlan,
    ExitReason,
    evaluate_exit,
    select_exit_plan,
)


class TradeDecision(StrEnum):
    """Final decision after all gates."""
    ACCEPT_PAPER_SIMULATION = "ACCEPT_PAPER_SIMULATION"
    REJECT_CIRCUIT_BREAKER = "REJECT_CIRCUIT_BREAKER"
    REJECT_KELLY_NO_EDGE = "REJECT_KELLY_NO_EDGE"
    REJECT_LEADER_EJECTED = "REJECT_LEADER_EJECTED"
    REJECT_SCORING = "REJECT_SCORING"
    REJECT_SAFETY = "REJECT_SAFETY"


@dataclass(slots=True)
class ViralBotSignal:
    """A fully evaluated signal ready for paper simulation or rejection."""
    signal_id: str
    leader_address: str
    coin: str
    side: str
    action_type: str
    decision: TradeDecision
    reasons: list[str]

    # Scoring output
    copy_score: RealtimeCopyScore | None = None

    # Kelly sizing output
    kelly_result: KellySizingResult | None = None
    position_size_usdt: float = 0.0

    # Circuit breaker state
    circuit_state: CircuitState = CircuitState.NORMAL
    sizing_multiplier: float = 1.0

    # Exit plan
    exit_plan: ExitPlan | None = None

    # Timing metrics (time-to-copy tracking)
    signal_detected_at_ms: int = 0
    decision_made_at_ms: int = 0
    time_to_decide_ms: int = 0

    # Leader performance context
    leader_status: str = "UNKNOWN"
    leader_session_pnl_usdt: float = 0.0

    @property
    def accepted(self) -> bool:
        return self.decision == TradeDecision.ACCEPT_PAPER_SIMULATION


@dataclass
class ViralBotEngine:
    """Main orchestrator for the viral-bot-inspired copy trading simulation.

    Integrates:
    - RealtimeCopyScore (edge calculation + cost model)
    - Kelly Criterion (position sizing)
    - Circuit Breaker (drawdown/streak protection)
    - Leader PnL Tracker (attribution + auto-rotation)
    - Enhanced Exit System (breakeven, time stops, adaptive trailing)

    PAPER SIMULATION ONLY. No real orders ever.
    """

    # Configuration
    copy_config: RealtimeCopyRiskConfig = field(default_factory=RealtimeCopyRiskConfig)
    kelly_config: KellySizingConfig = field(default_factory=KellySizingConfig)
    circuit_config: CircuitBreakerConfig = field(default_factory=CircuitBreakerConfig)

    # State
    circuit_state: CircuitBreakerState = field(default_factory=CircuitBreakerState)
    leader_tracker: LeaderPnLTracker = field(default_factory=LeaderPnLTracker)

    # Session metrics
    total_signals_evaluated: int = 0
    total_accepted: int = 0
    total_rejected: int = 0
    total_circuit_breaker_blocks: int = 0
    total_kelly_rejects: int = 0
    total_leader_ejects: int = 0
    avg_time_to_decide_ms: float = 0.0

    # Ejected leaders (won't accept signals from these)
    _ejected_leaders: set[str] = field(default_factory=set)

    def evaluate_signal(
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
    ) -> ViralBotSignal:
        """Full evaluation pipeline for a copy signal.

        Pipeline order:
        1. Check if leader is ejected
        2. Score signal (edge + costs)
        3. Check circuit breaker
        4. Kelly Criterion sizing
        5. Select exit plan
        6. Final decision

        Returns ViralBotSignal with full attribution.
        """
        start_ms = int(time.time() * 1000)
        self.total_signals_evaluated += 1
        reasons: list[str] = []

        # ── Gate 1: Leader ejection check ──────────────────────────
        leader_addr = leader_address.lower()
        if leader_addr in self._ejected_leaders:
            self.total_rejected += 1
            self.total_leader_ejects += 1
            return ViralBotSignal(
                signal_id=signal_id,
                leader_address=leader_addr,
                coin=coin,
                side=side,
                action_type=action_type,
                decision=TradeDecision.REJECT_LEADER_EJECTED,
                reasons=["leader_ejected_from_session"],
                signal_detected_at_ms=start_ms,
                decision_made_at_ms=int(time.time() * 1000),
                time_to_decide_ms=int(time.time() * 1000) - start_ms,
                leader_status="EJECTED",
            )

        # ── Gate 2: Signal scoring (edge + cost model) ─────────────
        score_input = RealtimeCopyScoreInput(
            action_type=action_type,
            direction=side,
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
        )
        copy_score = score_realtime_copy_candidate(score_input, config=self.copy_config)

        if not copy_score.accepted:
            self.total_rejected += 1
            end_ms = int(time.time() * 1000)
            return ViralBotSignal(
                signal_id=signal_id,
                leader_address=leader_addr,
                coin=coin,
                side=side,
                action_type=action_type,
                decision=TradeDecision.REJECT_SCORING,
                reasons=copy_score.refusal_reasons,
                copy_score=copy_score,
                signal_detected_at_ms=start_ms,
                decision_made_at_ms=end_ms,
                time_to_decide_ms=end_ms - start_ms,
            )

        # ── Gate 3: Circuit breaker ────────────────────────────────
        self.circuit_state = evaluate_circuit_breaker(
            self.circuit_state, self.circuit_config
        )

        if self.circuit_state.state in {CircuitState.PAUSED, CircuitState.HALTED}:
            self.total_rejected += 1
            self.total_circuit_breaker_blocks += 1
            end_ms = int(time.time() * 1000)
            return ViralBotSignal(
                signal_id=signal_id,
                leader_address=leader_addr,
                coin=coin,
                side=side,
                action_type=action_type,
                decision=TradeDecision.REJECT_CIRCUIT_BREAKER,
                reasons=[f"circuit_breaker_{self.circuit_state.state.value}",
                         *self.circuit_state.reasons],
                copy_score=copy_score,
                circuit_state=self.circuit_state.state,
                signal_detected_at_ms=start_ms,
                decision_made_at_ms=end_ms,
                time_to_decide_ms=end_ms - start_ms,
            )

        sizing_multiplier = self.circuit_state.sizing_multiplier

        # ── Gate 4: Kelly Criterion sizing ─────────────────────────
        kelly_result = kelly_criterion_size(
            edge_remaining_bps=copy_score.edge_remaining_bps or 0.0,
            leader_score=leader_score,
            consensus_wallets=consensus_wallets,
            win_rate_estimate=leader_win_rate,
            current_open_exposure_usdt=current_open_exposure_usdt,
            leader_notional_usdt=leader_notional_usdt,
            config=self.kelly_config,
        )

        if kelly_result.position_size_usdt <= 0:
            self.total_rejected += 1
            self.total_kelly_rejects += 1
            end_ms = int(time.time() * 1000)
            return ViralBotSignal(
                signal_id=signal_id,
                leader_address=leader_addr,
                coin=coin,
                side=side,
                action_type=action_type,
                decision=TradeDecision.REJECT_KELLY_NO_EDGE,
                reasons=["kelly_sizing_zero", *kelly_result.warnings],
                copy_score=copy_score,
                kelly_result=kelly_result,
                circuit_state=self.circuit_state.state,
                sizing_multiplier=sizing_multiplier,
                signal_detected_at_ms=start_ms,
                decision_made_at_ms=int(time.time() * 1000),
                time_to_decide_ms=int(time.time() * 1000) - start_ms,
            )

        # Apply circuit breaker sizing multiplier
        final_size = kelly_result.position_size_usdt * sizing_multiplier

        # ── Gate 5: Select exit plan ───────────────────────────────
        exit_plan = select_exit_plan(
            signal_id,
            edge_remaining_bps=copy_score.edge_remaining_bps or 0.0,
            consensus_wallets=consensus_wallets,
            leader_score=leader_score,
        )

        # ── Gate 6: Final acceptance ───────────────────────────────
        # Get leader performance context
        leader_perf = self.leader_tracker.get_leader_performance(leader_addr)
        leader_status = leader_perf.status if leader_perf else "NEW"
        leader_pnl = leader_perf.total_pnl_usdt if leader_perf else 0.0

        self.total_accepted += 1
        end_ms = int(time.time() * 1000)
        time_to_decide = end_ms - start_ms

        # Update rolling average
        n = self.total_signals_evaluated
        self.avg_time_to_decide_ms = (
            self.avg_time_to_decide_ms * (n - 1) + time_to_decide
        ) / n

        return ViralBotSignal(
            signal_id=signal_id,
            leader_address=leader_addr,
            coin=coin,
            side=side,
            action_type=action_type,
            decision=TradeDecision.ACCEPT_PAPER_SIMULATION,
            reasons=["all_gates_passed"],
            copy_score=copy_score,
            kelly_result=kelly_result,
            position_size_usdt=round(final_size, 2),
            circuit_state=self.circuit_state.state,
            sizing_multiplier=sizing_multiplier,
            exit_plan=exit_plan,
            signal_detected_at_ms=start_ms,
            decision_made_at_ms=end_ms,
            time_to_decide_ms=time_to_decide,
            leader_status=leader_status,
            leader_session_pnl_usdt=leader_pnl,
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
    ) -> None:
        """Record a closed paper trade for tracking and circuit breaker.

        This updates:
        1. Per-leader PnL tracker
        2. Circuit breaker state
        3. Auto-eject check
        """
        hold_duration_ms = int((exit_timestamp - entry_timestamp) * 1000)

        # Update leader tracker
        trade_record = LeaderTradeRecord(
            leader_address=leader_address.lower(),
            coin=coin,
            side=side,
            entry_price=entry_price,
            exit_price=exit_price,
            notional_usdt=notional_usdt,
            pnl_usdt=pnl_usdt,
            pnl_bps=pnl_bps,
            entry_timestamp=entry_timestamp,
            exit_timestamp=exit_timestamp,
            hold_duration_ms=hold_duration_ms,
            signal_age_at_entry_ms=signal_age_at_entry_ms,
        )
        self.leader_tracker.record_trade(trade_record)

        # Update circuit breaker
        self.circuit_state = record_trade_result(
            self.circuit_state, pnl_bps, pnl_usdt
        )

        # Check if leader should be ejected
        should_eject, reason = self.leader_tracker.should_eject_leader(
            leader_address
        )
        if should_eject:
            self._ejected_leaders.add(leader_address.lower())

    def get_session_report(self) -> dict:
        """Generate session report (Job C pattern from LearnWithMeAI)."""
        leader_summary = self.leader_tracker.get_session_summary()
        circuit = self.circuit_state

        return {
            # Session overview
            "total_signals_evaluated": self.total_signals_evaluated,
            "total_accepted": self.total_accepted,
            "total_rejected": self.total_rejected,
            "acceptance_rate": (
                self.total_accepted / max(1, self.total_signals_evaluated)
            ),

            # Rejection breakdown
            "circuit_breaker_blocks": self.total_circuit_breaker_blocks,
            "kelly_rejects": self.total_kelly_rejects,
            "leader_ejects": self.total_leader_ejects,
            "scoring_rejects": (
                self.total_rejected
                - self.total_circuit_breaker_blocks
                - self.total_kelly_rejects
                - self.total_leader_ejects
            ),

            # Circuit breaker
            "circuit_state": circuit.state.value,
            "session_pnl_usdt": round(circuit.session_pnl_usdt, 2),
            "current_equity_usdt": round(circuit.current_equity_usdt, 2),
            "peak_equity_usdt": round(circuit.peak_equity_usdt, 2),
            "drawdown_pct": round(
                (circuit.peak_equity_usdt - circuit.current_equity_usdt)
                / max(1, circuit.peak_equity_usdt) * 100, 2
            ),
            "consecutive_losses": circuit.consecutive_losses,

            # Leader performance
            **leader_summary,

            # Latency
            "avg_time_to_decide_ms": round(self.avg_time_to_decide_ms, 1),

            # Ejected leaders
            "ejected_leaders": list(self._ejected_leaders),

            # Safety confirmation
            "real_orders_created": 0,
            "real_money_used": 0,
            "key_material_used": 0,
            "simulation_only": True,
        }

    def get_active_leaders(self) -> list[str]:
        """Get leaders not yet ejected (for shortlist filtering)."""
        all_leaders = set(
            p.leader_address
            for p in self.leader_tracker.get_all_performances()
        )
        return sorted(all_leaders - self._ejected_leaders)

    def force_eject_leader(self, leader_address: str) -> None:
        """Manually eject a leader."""
        self._ejected_leaders.add(leader_address.lower())

    def reset_ejections(self) -> None:
        """Reset all ejections (for new session)."""
        self._ejected_leaders.clear()
