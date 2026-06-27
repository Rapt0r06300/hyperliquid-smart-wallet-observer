"""Decision tuning profiles for dYdX v4 paper simulation.

The goal is not a magical perfect threshold. The goal is an adaptive setup:
open more when confluence is excellent, reduce size when promising but imperfect,
and block only clear bad cases. Pure/read-only; no orders, no secrets, no network.
"""

from __future__ import annotations

from dataclasses import dataclass
try:
    from enum import StrEnum
except ImportError:  # pragma: no cover
    from enum import Enum

    class StrEnum(str, Enum):
        def __str__(self) -> str:
            return self.value

from hyper_smart_observer.dydx_v4.adaptive_risk import AdaptiveRiskProfile
from hyper_smart_observer.dydx_v4.signal_quality import QualityProfile
from hyper_smart_observer.dydx_v4.tremor_engine import TremorConfig


class TuningMode(StrEnum):
    PROTECTIVE = "protective"
    BALANCED = "balanced"
    OPPORTUNISTIC = "opportunistic"


@dataclass(frozen=True)
class DecisionTuningProfile:
    mode: TuningMode
    tremor: TremorConfig
    quality: QualityProfile
    risk: AdaptiveRiskProfile
    notes: tuple[str, ...]


def protective_profile() -> DecisionTuningProfile:
    return DecisionTuningProfile(
        mode=TuningMode.PROTECTIVE,
        tremor=TremorConfig(
            min_watch_score=3.5,
            min_paper_candidate_score=7.2,
            max_signal_age_ms=18_000,
            already_moved_bps=70.0,
            min_leading_wallets=1,
            min_consensus_wallets=3,
            min_edge_bps=6.0,
            min_flow_volume_usdc=18_000.0,
            min_flow_imbalance=0.70,
            min_flow_trades=8,
        ),
        quality=QualityProfile(
            min_score=78.0,
            min_tremor_score=7.2,
            min_edge_bps=6.0,
            max_signal_age_ms=18_000,
            min_wallets=3,
            min_flow_imbalance=0.70,
            min_flow_volume_usdc=18_000.0,
            block_after_move=True,
            block_choppy=True,
        ),
        risk=AdaptiveRiskProfile(
            min_quality_score=66.0,
            normal_quality_score=78.0,
            boost_quality_score=92.0,
            min_edge_bps=6.0,
            strong_edge_bps=24.0,
            max_signal_age_ms=18_000,
            soft_age_ms=7_000,
            max_spread_bps=24.0,
            max_slippage_bps=10.0,
            max_market_exposure_usdc=150.0,
            max_same_side_correlated=3,
            min_size_multiplier=0.20,
            max_size_multiplier=1.05,
        ),
        notes=("Use after weak session, high fees, unstable data, or too many bad closes.",),
    )


def balanced_profile() -> DecisionTuningProfile:
    return DecisionTuningProfile(
        mode=TuningMode.BALANCED,
        tremor=TremorConfig(
            min_watch_score=3.0,
            min_paper_candidate_score=6.5,
            max_signal_age_ms=30_000,
            already_moved_bps=90.0,
            min_leading_wallets=1,
            min_consensus_wallets=2,
            min_edge_bps=3.0,
            min_flow_volume_usdc=10_000.0,
            min_flow_imbalance=0.65,
            min_flow_trades=5,
        ),
        quality=QualityProfile(
            min_score=72.0,
            min_tremor_score=6.5,
            min_edge_bps=3.0,
            max_signal_age_ms=30_000,
            min_wallets=2,
            min_flow_imbalance=0.62,
            min_flow_volume_usdc=10_000.0,
            block_after_move=True,
            block_choppy=True,
        ),
        risk=AdaptiveRiskProfile(
            min_quality_score=58.0,
            normal_quality_score=72.0,
            boost_quality_score=88.0,
            min_edge_bps=3.0,
            strong_edge_bps=18.0,
            max_signal_age_ms=30_000,
            soft_age_ms=12_000,
            max_spread_bps=35.0,
            max_slippage_bps=14.0,
            max_market_exposure_usdc=220.0,
            max_same_side_correlated=5,
            min_size_multiplier=0.25,
            max_size_multiplier=1.25,
        ),
        notes=("Default profile: keeps engine active without accepting weak setups.",),
    )


def opportunistic_profile() -> DecisionTuningProfile:
    return DecisionTuningProfile(
        mode=TuningMode.OPPORTUNISTIC,
        tremor=TremorConfig(
            min_watch_score=2.7,
            min_paper_candidate_score=6.1,
            max_signal_age_ms=35_000,
            already_moved_bps=105.0,
            min_leading_wallets=1,
            min_consensus_wallets=2,
            min_edge_bps=2.5,
            min_flow_volume_usdc=8_000.0,
            min_flow_imbalance=0.62,
            min_flow_trades=4,
        ),
        quality=QualityProfile(
            min_score=68.0,
            min_tremor_score=6.1,
            min_edge_bps=2.5,
            max_signal_age_ms=35_000,
            min_wallets=2,
            min_flow_imbalance=0.60,
            min_flow_volume_usdc=8_000.0,
            block_after_move=True,
            block_choppy=True,
        ),
        risk=AdaptiveRiskProfile(
            min_quality_score=54.0,
            normal_quality_score=68.0,
            boost_quality_score=86.0,
            min_edge_bps=2.5,
            strong_edge_bps=16.0,
            max_signal_age_ms=35_000,
            soft_age_ms=15_000,
            max_spread_bps=40.0,
            max_slippage_bps=16.0,
            max_market_exposure_usdc=260.0,
            max_same_side_correlated=5,
            min_size_multiplier=0.18,
            max_size_multiplier=1.35,
        ),
        notes=("Use only when data is stable and diagnostics are healthy; still blocks after-move/choppy setups.",),
    )


def get_tuning_profile(mode: str | TuningMode = TuningMode.BALANCED) -> DecisionTuningProfile:
    m = TuningMode(str(mode).lower())
    if m == TuningMode.PROTECTIVE:
        return protective_profile()
    if m == TuningMode.OPPORTUNISTIC:
        return opportunistic_profile()
    return balanced_profile()


def choose_mode_from_health(*, winrate: float, profit_factor: float, closed_trades: int, fallback_share: float = 0.0) -> TuningMode:
    """Simple health-based mode selector for paper simulation diagnostics."""
    if closed_trades < 8:
        return TuningMode.BALANCED
    if fallback_share > 0.35:
        return TuningMode.PROTECTIVE
    if winrate < 0.42 or profit_factor < 0.85:
        return TuningMode.PROTECTIVE
    if winrate >= 0.55 and profit_factor >= 1.25:
        return TuningMode.OPPORTUNISTIC
    return TuningMode.BALANCED


__all__ = [
    "DecisionTuningProfile",
    "TuningMode",
    "balanced_profile",
    "choose_mode_from_health",
    "get_tuning_profile",
    "opportunistic_profile",
    "protective_profile",
]
