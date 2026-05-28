from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from hl_observer.hyperliquid.schemas import SignalCandidate, SignalDecision, RiskDecision
from hl_observer.exits.exit_engine import ExitPlan, build_default_exit_plan

@dataclass
class DecisionContext:
    signal: SignalCandidate
    wallet_score: float
    equity_usdt: float
    open_positions_count: int
    total_exposure_usdt: float
    market_regime: str = "unknown"

@dataclass
class UnifiedDecision:
    allowed: bool
    decision: SignalDecision
    reasons: list[str] = field(default_factory=list)
    exit_plan: ExitPlan | None = None
    simulated_notional: float = 0.0

class UnifiedDecisionEngine:
    """Shared logic for both live simulation and historical backtesting.

    Ensures identical trading rules, fee modeling, and fill simulation
    across all environments.
    """

    def __init__(self, config: Any):
        self.config = config

    def evaluate(self, context: DecisionContext) -> UnifiedDecision:
        reasons = []

        # 1. Base Signal Decision
        # Check for REJECT_NO_TRADE (legacy/root) or any REJECT_* (src)
        sig_decision = str(context.signal.decision)
        if "REJECT" in sig_decision:
            return UnifiedDecision(
                allowed=False,
                decision=context.signal.decision,
                reasons=context.signal.refusal_reasons or ["signal_rejected_by_detector"]
            )

        # 2. Wallet Score Gate
        if context.wallet_score < self.config.risk.min_wallet_score:
            reasons.append("REJECT_WALLET_SCORE_LOW")

        # 3. Portfolio Limits
        # Prefer Settings based paths
        max_open = getattr(self.config, "paper_max_open_trades", 3)
        if context.open_positions_count >= max_open:
            reasons.append("REJECT_MAX_OPEN_TRADES")

        max_total = getattr(self.config, "paper_max_total_exposure", 200.0)
        notional_per_pos = getattr(self.config, "paper_max_position_notional", 50.0)
        if context.total_exposure_usdt + notional_per_pos > max_total:
            reasons.append("REJECT_MAX_TOTAL_EXPOSURE")

        # 4. Edge Remaining Gate
        if context.signal.edge_remaining_bps is None or context.signal.edge_remaining_bps < self.config.risk.min_edge_required_bps:
            reasons.append("REJECT_EDGE_TOO_LOW")

        if reasons:
            # Use a generic reject if multiple reasons exist
            return UnifiedDecision(
                allowed=False,
                decision=SignalDecision.REJECT_WALLET_UNPROVEN,
                reasons=reasons
            )

        # 5. Success: Build Exit Plan and Sizing
        exit_plan = build_default_exit_plan(context.signal.candidate_id)

        return UnifiedDecision(
            allowed=True,
            decision=SignalDecision.PAPER_TRADE,
            reasons=["ACCEPTED_FOR_LOCAL_SIMULATION"],
            exit_plan=exit_plan,
            simulated_notional=notional_per_pos
        )
