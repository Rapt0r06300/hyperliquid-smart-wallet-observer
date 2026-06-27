"""Adaptive decision orchestrator for dYdX v4 paper simulation.

Combines TremorEngine, SignalQuality and AdaptiveRisk into one explainable
paper decision. It is intentionally pure/read-only: no network, no orders,
no private keys, no mutation.
"""

from __future__ import annotations

from dataclasses import dataclass, field
try:
    from enum import StrEnum
except ImportError:  # pragma: no cover
    from enum import Enum

    class StrEnum(str, Enum):
        def __str__(self) -> str:
            return self.value

from hyper_smart_observer.dydx_v4.adaptive_risk import (
    AdaptiveRiskDecision,
    AdaptiveRiskInput,
    AdaptiveRiskProfile,
    RiskAction,
    evaluate_adaptive_risk,
)
from hyper_smart_observer.dydx_v4.signal_quality import QualityDecision
from hyper_smart_observer.dydx_v4.tremor_engine import TremorObservation
from hyper_smart_observer.dydx_v4.tremor_quality_adapter import (
    TremorQualityResult,
    evaluate_tremor_quality,
)


class PaperDecision(StrEnum):
    NO_TRADE = "NO_TRADE"
    WATCH = "WATCH"
    PAPER_OPEN_REDUCED = "PAPER_OPEN_REDUCED"
    PAPER_OPEN = "PAPER_OPEN"
    PAPER_OPEN_BOOSTED = "PAPER_OPEN_BOOSTED"


@dataclass(frozen=True)
class DecisionContext:
    spread_bps: float = 0.0
    slippage_bps: float = 0.0
    open_positions: int = 0
    current_market_exposure_usdc: float = 0.0
    correlated_same_side_count: int = 0
    consecutive_losses: int = 0
    daily_pnl_usdc: float = 0.0
    base_notional_usdc: float = 75.0
    max_notional_usdc: float = 100.0


@dataclass(frozen=True)
class OrchestratedDecision:
    decision: PaperDecision
    final_notional_usdc: float
    size_multiplier: float
    tremor_quality: TremorQualityResult
    adaptive_risk: AdaptiveRiskDecision
    reasons: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    paper_only: bool = True
    read_only: bool = True

    @property
    def can_open(self) -> bool:
        return self.decision in {
            PaperDecision.PAPER_OPEN_REDUCED,
            PaperDecision.PAPER_OPEN,
            PaperDecision.PAPER_OPEN_BOOSTED,
        }

    def to_dict(self) -> dict:
        return {
            "decision": self.decision.value,
            "can_open": self.can_open,
            "final_notional_usdc": round(self.final_notional_usdc, 6),
            "size_multiplier": round(self.size_multiplier, 6),
            "tremor_quality": self.tremor_quality.to_dict(),
            "adaptive_risk": self.adaptive_risk.to_dict(),
            "reasons": list(self.reasons),
            "notes": list(self.notes),
            "paper_only": self.paper_only,
            "read_only": self.read_only,
        }


def _risk_input(obs: TremorObservation, tq: TremorQualityResult, ctx: DecisionContext) -> AdaptiveRiskInput:
    return AdaptiveRiskInput(
        market_id=obs.market_id,
        side=obs.direction,
        quality_score=tq.quality.score,
        tremor_score=tq.tremor.intensity_score,
        tremor_phase=tq.tremor.timeline_phase,
        edge_remaining_bps=float(obs.edge_remaining_bps or 0.0),
        signal_age_ms=obs.signal_age_ms,
        spread_bps=ctx.spread_bps,
        slippage_bps=ctx.slippage_bps,
        market_regime=obs.market_regime,
        wallet_count=obs.consensus_wallets,
        flow_imbalance=obs.flow_imbalance,
        open_positions=ctx.open_positions,
        current_market_exposure_usdc=ctx.current_market_exposure_usdc,
        correlated_same_side_count=ctx.correlated_same_side_count,
        consecutive_losses=ctx.consecutive_losses,
        daily_pnl_usdc=ctx.daily_pnl_usdc,
        data_source=obs.source,
    )


def orchestrate_paper_decision(
    obs: TremorObservation,
    ctx: DecisionContext | None = None,
    risk_profile: AdaptiveRiskProfile | None = None,
) -> OrchestratedDecision:
    context = ctx or DecisionContext()
    tq = evaluate_tremor_quality(obs, spread_bps=context.spread_bps, slippage_bps=context.slippage_bps)
    risk = evaluate_adaptive_risk(_risk_input(obs, tq, context), risk_profile)

    reasons: list[str] = []
    notes: list[str] = []
    reasons.extend(tq.tremor.reasons)
    reasons.extend(tq.quality.reasons)
    reasons.extend(risk.reasons)
    notes.extend(tq.quality.notes)
    notes.extend(risk.notes)

    if tq.quality.decision == QualityDecision.REJECT or risk.action == RiskAction.BLOCK:
        return OrchestratedDecision(PaperDecision.NO_TRADE, 0.0, 0.0, tq, risk, reasons, notes)

    if tq.quality.decision == QualityDecision.WATCH:
        return OrchestratedDecision(PaperDecision.WATCH, 0.0, 0.0, tq, risk, reasons or ["WATCH_ONLY"], notes)

    if not tq.tremor.is_actionable_paper_candidate:
        return OrchestratedDecision(PaperDecision.WATCH, 0.0, 0.0, tq, risk, reasons or ["TREMOR_NOT_ACTIONABLE"], notes)

    base = max(0.0, context.base_notional_usdc)
    notional = min(context.max_notional_usdc, risk.apply_to_notional(base))

    if risk.action == RiskAction.REDUCE:
        return OrchestratedDecision(PaperDecision.PAPER_OPEN_REDUCED, notional, risk.size_multiplier, tq, risk, reasons, notes)
    if risk.action == RiskAction.BOOST:
        return OrchestratedDecision(PaperDecision.PAPER_OPEN_BOOSTED, notional, risk.size_multiplier, tq, risk, reasons, notes)
    return OrchestratedDecision(PaperDecision.PAPER_OPEN, notional, risk.size_multiplier, tq, risk, reasons, notes)


__all__ = [
    "DecisionContext",
    "OrchestratedDecision",
    "PaperDecision",
    "orchestrate_paper_decision",
]
