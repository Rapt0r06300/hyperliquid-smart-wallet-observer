"""Decision Intelligence V2 for dYdX paper mode.

This is the pro layer above tuned_decision:
- avoids overtrading with opportunity budgets;
- uses fractional confidence sizing rather than all-in thresholds;
- keeps a small exploration lane for promising but unproven setups;
- protects after weak diagnostics without killing the scanner;
- returns explicit reasons for every throttle.

Pure/read-only. No network, no orders, no private keys.
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

from hyper_smart_observer.dydx_v4.decision_tuning import (
    TuningMode,
    choose_mode_from_health,
    get_tuning_profile,
)
from hyper_smart_observer.dydx_v4.tremor_engine import TremorObservation
from hyper_smart_observer.dydx_v4.tuned_decision import (
    TunedDecisionContext,
    TunedPaperAction,
    TunedPaperDecision,
    tuned_paper_decision,
)


class IntelligenceAction(StrEnum):
    NO_TRADE = "NO_TRADE"
    WATCH = "WATCH"
    MICRO_EXPLORE = "MICRO_EXPLORE"
    OPEN_REDUCED = "OPEN_REDUCED"
    OPEN_NORMAL = "OPEN_NORMAL"
    OPEN_BOOSTED = "OPEN_BOOSTED"


@dataclass(frozen=True)
class SessionHealth:
    closed_trades: int = 0
    winrate: float = 0.0
    profit_factor: float = 0.0
    fallback_share: float = 0.0
    consecutive_losses: int = 0
    daily_pnl_usdc: float = 0.0
    open_positions: int = 0


@dataclass(frozen=True)
class OpportunityBudget:
    max_open_positions: int = 25
    max_new_positions_per_hour: int = 10
    max_same_market_positions: int = 2
    max_reduced_positions_per_hour: int = 6
    max_explore_positions_per_hour: int = 2
    min_minutes_between_same_market: float = 3.0


@dataclass(frozen=True)
class BudgetState:
    new_positions_last_hour: int = 0
    reduced_positions_last_hour: int = 0
    explore_positions_last_hour: int = 0
    same_market_open_positions: int = 0
    minutes_since_same_market_open: float = 999.0


@dataclass(frozen=True)
class DecisionIntelligenceConfig:
    mode: str = "auto"
    base_notional_usdc: float = 75.0
    max_notional_usdc: float = 100.0
    micro_explore_notional_usdc: float = 12.0
    min_micro_explore_tremor: float = 6.8
    min_micro_explore_quality: float = 64.0
    min_micro_explore_edge_bps: float = 5.0
    allow_micro_explore: bool = True
    hard_daily_loss_usdc: float = -45.0
    hard_consecutive_losses: int = 6
    budget: OpportunityBudget = field(default_factory=OpportunityBudget)


@dataclass(frozen=True)
class DecisionIntelligenceResult:
    action: IntelligenceAction
    mode: TuningMode
    notional_usdc: float
    tuned: TunedPaperDecision
    reasons: list[str]
    notes: list[str]
    paper_only: bool = True
    read_only: bool = True

    @property
    def can_open(self) -> bool:
        return self.action in {
            IntelligenceAction.MICRO_EXPLORE,
            IntelligenceAction.OPEN_REDUCED,
            IntelligenceAction.OPEN_NORMAL,
            IntelligenceAction.OPEN_BOOSTED,
        }

    def to_dict(self) -> dict:
        return {
            "action": self.action.value,
            "mode": self.mode.value,
            "can_open": self.can_open,
            "notional_usdc": round(self.notional_usdc, 6),
            "tuned": self.tuned.to_dict(),
            "reasons": list(self.reasons),
            "notes": list(self.notes),
            "paper_only": self.paper_only,
            "read_only": self.read_only,
        }


def select_mode(health: SessionHealth, requested: str = "auto") -> TuningMode:
    if requested != "auto":
        return TuningMode(str(requested).lower())
    return choose_mode_from_health(
        winrate=health.winrate,
        profit_factor=health.profit_factor,
        closed_trades=health.closed_trades,
        fallback_share=health.fallback_share,
    )


def _base_context(ctx: TunedDecisionContext | None, cfg: DecisionIntelligenceConfig, health: SessionHealth) -> TunedDecisionContext:
    if ctx is None:
        return TunedDecisionContext(
            open_positions=health.open_positions,
            consecutive_losses=health.consecutive_losses,
            daily_pnl_usdc=health.daily_pnl_usdc,
            base_notional_usdc=cfg.base_notional_usdc,
            max_notional_usdc=cfg.max_notional_usdc,
        )
    return TunedDecisionContext(
        spread_bps=ctx.spread_bps,
        slippage_bps=ctx.slippage_bps,
        open_positions=ctx.open_positions,
        market_exposure_usdc=ctx.market_exposure_usdc,
        correlated_same_side_count=ctx.correlated_same_side_count,
        consecutive_losses=ctx.consecutive_losses,
        daily_pnl_usdc=ctx.daily_pnl_usdc,
        base_notional_usdc=cfg.base_notional_usdc,
        max_notional_usdc=cfg.max_notional_usdc,
    )


def _budget_blocks(budget: OpportunityBudget, state: BudgetState, ctx: TunedDecisionContext) -> list[str]:
    reasons: list[str] = []
    if ctx.open_positions >= budget.max_open_positions:
        reasons.append("BUDGET_MAX_OPEN_POSITIONS")
    if state.new_positions_last_hour >= budget.max_new_positions_per_hour:
        reasons.append("BUDGET_HOURLY_NEW_LIMIT")
    if state.same_market_open_positions >= budget.max_same_market_positions:
        reasons.append("BUDGET_SAME_MARKET_LIMIT")
    if state.minutes_since_same_market_open < budget.min_minutes_between_same_market:
        reasons.append("BUDGET_SAME_MARKET_COOLDOWN")
    return reasons


def _micro_explore_allowed(
    tuned: TunedPaperDecision,
    cfg: DecisionIntelligenceConfig,
    state: BudgetState,
    health: SessionHealth,
) -> bool:
    if not cfg.allow_micro_explore:
        return False
    if state.explore_positions_last_hour >= cfg.budget.max_explore_positions_per_hour:
        return False
    if health.consecutive_losses >= 3 or health.daily_pnl_usdc <= cfg.hard_daily_loss_usdc * 0.5:
        return False
    return (
        tuned.action == TunedPaperAction.WATCH
        and tuned.tremor.intensity_score >= cfg.min_micro_explore_tremor
        and tuned.quality.score >= cfg.min_micro_explore_quality
        and float(tuned.tremor.edge_remaining_bps or 0.0) >= cfg.min_micro_explore_edge_bps
        and tuned.tremor.timeline_phase != "AFTER_MOVE"
    )


def decision_intelligence_v2(
    obs: TremorObservation,
    *,
    health: SessionHealth | None = None,
    budget_state: BudgetState | None = None,
    ctx: TunedDecisionContext | None = None,
    config: DecisionIntelligenceConfig | None = None,
) -> DecisionIntelligenceResult:
    cfg = config or DecisionIntelligenceConfig()
    h = health or SessionHealth()
    state = budget_state or BudgetState()
    mode = select_mode(h, cfg.mode)
    context = _base_context(ctx, cfg, h)
    tuned = tuned_paper_decision(obs, ctx=context, mode=get_tuning_profile(mode))

    reasons = list(tuned.reasons)
    notes = list(tuned.notes)

    if h.daily_pnl_usdc <= cfg.hard_daily_loss_usdc:
        return DecisionIntelligenceResult(IntelligenceAction.NO_TRADE, mode, 0.0, tuned, reasons + ["HARD_DAILY_LOSS_GUARD"], notes)
    if h.consecutive_losses >= cfg.hard_consecutive_losses:
        return DecisionIntelligenceResult(IntelligenceAction.NO_TRADE, mode, 0.0, tuned, reasons + ["HARD_CONSECUTIVE_LOSS_GUARD"], notes)

    budget_reasons = _budget_blocks(cfg.budget, state, context)
    if budget_reasons and tuned.can_open:
        # Do not kill the scanner: downgrade to WATCH instead of pretending the signal is bad.
        return DecisionIntelligenceResult(IntelligenceAction.WATCH, mode, 0.0, tuned, reasons + budget_reasons, notes + ["budget_throttle_watch"])

    if tuned.can_open:
        if tuned.action == TunedPaperAction.OPEN_BOOSTED:
            return DecisionIntelligenceResult(IntelligenceAction.OPEN_BOOSTED, mode, tuned.final_notional_usdc, tuned, reasons, notes)
        if tuned.action == TunedPaperAction.OPEN_NORMAL:
            return DecisionIntelligenceResult(IntelligenceAction.OPEN_NORMAL, mode, tuned.final_notional_usdc, tuned, reasons, notes)
        return DecisionIntelligenceResult(IntelligenceAction.OPEN_REDUCED, mode, tuned.final_notional_usdc, tuned, reasons, notes)

    if _micro_explore_allowed(tuned, cfg, state, h):
        return DecisionIntelligenceResult(
            IntelligenceAction.MICRO_EXPLORE,
            mode,
            min(cfg.micro_explore_notional_usdc, cfg.max_notional_usdc),
            tuned,
            reasons + ["MICRO_EXPLORE_PROMISING_WATCH"],
            notes,
        )

    if tuned.action == TunedPaperAction.WATCH:
        return DecisionIntelligenceResult(IntelligenceAction.WATCH, mode, 0.0, tuned, reasons, notes)
    return DecisionIntelligenceResult(IntelligenceAction.NO_TRADE, mode, 0.0, tuned, reasons, notes)


__all__ = [
    "BudgetState",
    "DecisionIntelligenceConfig",
    "DecisionIntelligenceResult",
    "IntelligenceAction",
    "OpportunityBudget",
    "SessionHealth",
    "decision_intelligence_v2",
    "select_mode",
]
