"""Paper-only strategy registry & intents (V12 capability M). Read-only / sim-only."""

from hl_observer.strategies.models import (
    ApprovedPaperIntent,
    IntentAction,
    IntentSide,
    PaperIntent,
    StrategyDefinition,
    StrategyKind,
    StrategyLane,
    StrategyState,
    approve_with_risk,
    is_actionable,
    make_strategy,
)
from hl_observer.strategies.paper_registry import PaperStrategyRegistry
from hl_observer.strategies.reference import CopyFollowStrategy, MarketMakingSimStrategy
from hl_observer.strategies.v14_profiles import V14StrategyProfile, register_v14_profiles, v14_default_profiles
from hl_observer.strategies.fusion_runtime import FusionRuntimeInput, FusionRuntimeResult, run_fusion_strategy_runtime
from hl_observer.strategies.external_github_bridge import (
    build_external_github_bridge_payload,
    discover_external_repo_capabilities,
    external_strategy_catalog,
    external_strategy_definitions,
    register_external_github_profiles,
)
from hl_observer.strategies.github_distillation import (
    DistilledGithubIdea,
    distillation_status_counts,
    priority_distillation_matrix,
)

__all__ = [
    "StrategyKind",
    "StrategyLane",
    "StrategyState",
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
    "V14StrategyProfile",
    "register_v14_profiles",
    "v14_default_profiles",
    "FusionRuntimeInput",
    "FusionRuntimeResult",
    "run_fusion_strategy_runtime",
    "build_external_github_bridge_payload",
    "discover_external_repo_capabilities",
    "external_strategy_catalog",
    "external_strategy_definitions",
    "register_external_github_profiles",
    "DistilledGithubIdea",
    "distillation_status_counts",
    "priority_distillation_matrix",
]
