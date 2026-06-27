"""Tuned adaptive paper decision flow.

Applies a DecisionTuningProfile consistently to TremorEngine, SignalQuality and
AdaptiveRisk. This is the recommended high-level decision helper for paper mode.
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
    RiskAction,
    evaluate_adaptive_risk,
)
from hyper_smart_observer.dydx_v4.decision_tuning import (
    DecisionTuningProfile,
    TuningMode,
    get_tuning_profile,
)
from hyper_smart_observer.dydx_v4.signal_quality import (
    QualityDecision,
    SignalQualityDecision,
    SignalQualityInput,
    evaluate_signal_quality,
)
from hyper_smart_observer.dydx_v4.tremor_engine import (
    TremorEvent,
    TremorObservation,
    evaluate_tremor,
)


class TunedPaperAction(StrEnum):
    NO_TRADE = "NO_TRADE"
    WATCH = "WATCH"
    OPEN_REDUCED = "OPEN_REDUCED"
    OPEN_NORMAL = "OPEN_NORMAL"
    OPEN_BOOSTED = "OPEN_BOOSTED"


@dataclass(frozen=True)
class TunedDecisionContext:
    spread_bps: float = 0.0
    slippage_bps: float = 0.0
    open_positions: int = 0
    market_exposure_usdc: float = 0.0
    correlated_same_side_count: int = 0
    consecutive_losses: int = 0
    daily_pnl_usdc: float = 0.0
    base_notional_usdc: float = 75.0
    max_notional_usdc: float = 100.0


@dataclass(frozen=True)
class TunedPaperDecision:
    action: TunedPaperAction
    mode: TuningMode
    final_notional_usdc: float
    tremor: TremorEvent
    quality: SignalQualityDecision
    risk: AdaptiveRiskDecision
    reasons: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    paper_only: bool = True
    read_only: bool = True

    @property
    def can_open(self) -> bool:
        return self.action in {
            TunedPaperAction.OPEN_REDUCED,
            TunedPaperAction.OPEN_NORMAL,
            TunedPaperAction.OPEN_BOOSTED,
        }

    def to_dict(self) -> dict:
        return {
            "action": self.action.value,
            "mode": self.mode.value,
            "can_open": self.can_open,
            "final_notional_usdc": round(self.final_notional_usdc, 6),
            "tremor": self.tremor.to_log_dict(),
            "quality": self.quality.to_dict(),
            "risk": self.risk.to_dict(),
            "reasons": list(self.reasons),
            "notes": list(self.notes),
            "paper_only": self.paper_only,
            "read_only": self.read_only,
        }


def _quality_input(tremor: TremorEvent, ctx: TunedDecisionContext) -> SignalQualityInput:
    return SignalQualityInput(
        market_id=tremor.market_id,
        side=tremor.direction,
        tremor_score=tremor.intensity_score,
        tremor_phase=tremor.timeline_phase,
        signal_age_ms=tremor.signal_age_ms,
        wallet_count=tremor.consensus_wallets,
        flow_imbalance=tremor.flow_imbalance,
        flow_volume_usdc=tremor.flow_volume_usdc,
        edge_remaining_bps=float(tremor.edge_remaining_bps or 0.0),
        market_regime=tremor.market_regime,
        data_source=tremor.source,
        spread_bps=ctx.spread_bps,
        slippage_bps=ctx.slippage_bps,
    )


def _risk_input(obs: TremorObservation, tremor: TremorEvent, quality: SignalQualityDecision, ctx: TunedDecisionContext) -> AdaptiveRiskInput:
    return AdaptiveRiskInput(
        market_id=obs.market_id,
        side=obs.direction,
        quality_score=quality.score,
        tremor_score=tremor.intensity_score,
        tremor_phase=tremor.timeline_phase,
        edge_remaining_bps=float(obs.edge_remaining_bps or 0.0),
        signal_age_ms=obs.signal_age_ms,
        spread_bps=ctx.spread_bps,
        slippage_bps=ctx.slippage_bps,
        market_regime=obs.market_regime,
        wallet_count=obs.consensus_wallets,
        flow_imbalance=obs.flow_imbalance,
        open_positions=ctx.open_positions,
        current_market_exposure_usdc=ctx.market_exposure_usdc,
        correlated_same_side_count=ctx.correlated_same_side_count,
        consecutive_losses=ctx.consecutive_losses,
        daily_pnl_usdc=ctx.daily_pnl_usdc,
        data_source=obs.source,
    )


def tuned_paper_decision(
    obs: TremorObservation,
    *,
    ctx: TunedDecisionContext | None = None,
    mode: str | TuningMode | DecisionTuningProfile = TuningMode.BALANCED,
) -> TunedPaperDecision:
    context = ctx or TunedDecisionContext()
    profile = mode if isinstance(mode, DecisionTuningProfile) else get_tuning_profile(mode)

    tremor = evaluate_tremor(obs, profile.tremor)
    quality = evaluate_signal_quality(_quality_input(tremor, context), profile.quality)
    risk = evaluate_adaptive_risk(_risk_input(obs, tremor, quality, context), profile.risk)

    reasons = list(tremor.reasons) + list(quality.reasons) + list(risk.reasons)
    notes = list(quality.notes) + list(risk.notes) + list(profile.notes)

    if quality.decision == QualityDecision.REJECT or risk.action == RiskAction.BLOCK:
        return TunedPaperDecision(TunedPaperAction.NO_TRADE, profile.mode, 0.0, tremor, quality, risk, reasons, notes)
    if quality.decision == QualityDecision.WATCH or not tremor.is_actionable_paper_candidate:
        return TunedPaperDecision(TunedPaperAction.WATCH, profile.mode, 0.0, tremor, quality, risk, reasons or ["WATCH_ONLY"], notes)

    final_notional = min(context.max_notional_usdc, risk.apply_to_notional(context.base_notional_usdc))
    if risk.action == RiskAction.REDUCE:
        action = TunedPaperAction.OPEN_REDUCED
    elif risk.action == RiskAction.BOOST:
        action = TunedPaperAction.OPEN_BOOSTED
    else:
        action = TunedPaperAction.OPEN_NORMAL
    return TunedPaperDecision(action, profile.mode, final_notional, tremor, quality, risk, reasons, notes)


__all__ = [
    "TunedDecisionContext",
    "TunedPaperAction",
    "TunedPaperDecision",
    "tuned_paper_decision",
]
