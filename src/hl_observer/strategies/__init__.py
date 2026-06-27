"""Paper-only strategy registry & intents (V12 capability M). Read-only / sim-only."""

from hl_observer.strategies.models import (
    ApprovedPaperIntent,
    IntentAction,
    IntentSide,
    PaperIntent,
    StrategyDefinition,
    StrategyKind,
    approve_with_risk,
    is_actionable,
    make_strategy,
)
from hl_observer.strategies.paper_registry import PaperStrategyRegistry
from hl_observer.strategies.reference import CopyFollowStrategy, MarketMakingSimStrategy

__all__ = [
    "StrategyKind",
    "IntentSide",
    "IntentAction",
    "PaperIntent",
    "ApprovedPaperIntent",
    "StrategyDefinition",
    "approve_with_risk",
    "is_actionable",
    "make_strategy",
    "PaperStrategyRegistry",
    "CopyFollowStrategy",
    "MarketMakingSimStrategy",
]
