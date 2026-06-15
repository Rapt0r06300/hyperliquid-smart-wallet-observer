"""Decision Intelligence V2 for dYdX paper mode.

This is the pro layer above tuned_decision:
- avoids overtrading with opportunity budgets;
- uses fractional confidence sizing rather than all-in thresholds;
- keeps a small exploration lane for promising but unproven setups;
- protects after weak diagnostics without killing the scanner;
- degrades size when data quality is weak instead of pretending confidence is high;
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
from hyper_smart_observer.dydx_v4.intelligence_director import assess_decision_intelligence
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
    cold_start_trades: int = 8
    cold_start_size_cap: float = 0.55
    weak_data_fallback_share: float = 0.35
    weak_data_size_cap: float = 0.50
    director_enabled: bool = True
    budget: OpportunityBudget = field(default_factory=OpportunityBudget)


@dataclass(frozen=True)
class DecisionIntelligenceResult:
    action: IntelligenceAction
    mode: TuningMode
    notional_usdc: float
    tuned: TunedPaperDecision
    reasons: list[str]
    notes: list[str]
    director: dict = field(default_factory=dict)
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
            "director": dict(self.director or {}),
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


def _quality_cap(h: SessionHealth, cfg: DecisionIntelligenceConfig) -> tuple[float, list[str]]:
    cap = 1.0
    notes: list[str] = []
    if h.closed_trades < cfg.cold_start_trades:
        cap = min(cap, cfg.cold_start_size_cap)
        notes.append("cold_start_size_cap")
    if h.fallback_share >= cfg.weak_data_fallback_share:
        cap = min(cap, cfg.weak_data_size_cap)
        notes.append("weak_data_size_cap")
    return cap, notes


def _capped_open_result(
    action: IntelligenceAction,
    mode: TuningMode,
    notional: float,
    tuned: TunedPaperDecision,
    reasons: list[str],
    notes: list[str],
    cap: float,
    cap_notes: list[str],
    director: dict | None = None,
) -> DecisionIntelligenceResult:
    if cap < 1.0:
        notional = max(0.0, notional * cap)
        notes = notes + cap_notes
        if action in {IntelligenceAction.OPEN_NORMAL, IntelligenceAction.OPEN_BOOSTED}:
            action = IntelligenceAction.OPEN_REDUCED
    return DecisionIntelligenceResult(action, mode, notional, tuned, reasons, notes, director or {})


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
    cap, cap_notes = _quality_cap(h, cfg)
    director_dict: dict = {}

    if cfg.director_enabled:
        director = assess_decision_intelligence(tuned, h, state, context)
        director_dict = director.to_dict()
        reasons += director.reasons
        notes += director.notes
        notes.append(f"director_net={director.net_score:.2f}")
        notes.append(f"director_risk={director.risk_score:.2f}")
        cap = min(cap, director.size_multiplier)
        if director.hard_block and tuned.can_open:
            return DecisionIntelligenceResult(
                IntelligenceAction.NO_TRADE,
                mode,
                0.0,
                tuned,
                reasons + ["DIRECTOR_HARD_BLOCK"],
                notes,
                director_dict,
            )
        if tuned.can_open and director.size_multiplier <= 0.0:
            return DecisionIntelligenceResult(
                IntelligenceAction.WATCH,
                mode,
                0.0,
                tuned,
                reasons + ["DIRECTOR_SIZE_ZERO"],
                notes,
                director_dict,
            )

    if h.daily_pnl_usdc <= cfg.hard_daily_loss_usdc:
        return DecisionIntelligenceResult(IntelligenceAction.NO_TRADE, mode, 0.0, tuned, reasons + ["HARD_DAILY_LOSS_GUARD"], notes, director_dict)
    if h.consecutive_losses >= cfg.hard_consecutive_losses:
        return DecisionIntelligenceResult(IntelligenceAction.NO_TRADE, mode, 0.0, tuned, reasons + ["HARD_CONSECUTIVE_LOSS_GUARD"], notes, director_dict)

    budget_reasons = _budget_blocks(cfg.budget, state, context)
    if budget_reasons and tuned.can_open:
        return DecisionIntelligenceResult(IntelligenceAction.WATCH, mode, 0.0, tuned, reasons + budget_reasons, notes + ["budget_throttle_watch"], director_dict)

    if tuned.can_open:
        if tuned.action == TunedPaperAction.OPEN_BOOSTED:
            return _capped_open_result(IntelligenceAction.OPEN_BOOSTED, mode, tuned.final_notional_usdc, tuned, reasons, notes, cap, cap_notes, director_dict)
        if tuned.action == TunedPaperAction.OPEN_NORMAL:
            return _capped_open_result(IntelligenceAction.OPEN_NORMAL, mode, tuned.final_notional_usdc, tuned, reasons, notes, cap, cap_notes, director_dict)
        return _capped_open_result(IntelligenceAction.OPEN_REDUCED, mode, tuned.final_notional_usdc, tuned, reasons, notes, cap, cap_notes, director_dict)

    if _micro_explore_allowed(tuned, cfg, state, h):
        micro_notional = min(cfg.micro_explore_notional_usdc * max(cap, 0.0), cfg.max_notional_usdc)
        if micro_notional > 0:
            return DecisionIntelligenceResult(
                IntelligenceAction.MICRO_EXPLORE,
                mode,
                micro_notional,
                tuned,
                reasons + ["MICRO_EXPLORE_PROMISING_WATCH"],
                notes,
                director_dict,
            )

    if tuned.action == TunedPaperAction.WATCH:
        return DecisionIntelligenceResult(IntelligenceAction.WATCH, mode, 0.0, tuned, reasons, notes, director_dict)
    return DecisionIntelligenceResult(IntelligenceAction.NO_TRADE, mode, 0.0, tuned, reasons, notes, director_dict)


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
