"""Paper-only strategy registry & intents (V12 capability M). Read-only / sim-only."""

from __future__ import annotations

from typing import Any

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
from hl_observer.strategies.v14_profiles import (
    V14StrategyProfile,
    register_v14_profiles,
    v14_default_profiles,
)

_LAZY_EXPORTS = {
    "FusionRuntimeInput": ("hl_observer.strategies.fusion_runtime", "FusionRuntimeInput"),
    "FusionRuntimeResult": ("hl_observer.strategies.fusion_runtime", "FusionRuntimeResult"),
    "run_fusion_strategy_runtime": (
        "hl_observer.strategies.fusion_runtime",
        "run_fusion_strategy_runtime",
    ),
    "build_external_github_bridge_payload": (
        "hl_observer.strategies.external_github_bridge",
        "build_external_github_bridge_payload",
    ),
    "discover_external_repo_capabilities": (
        "hl_observer.strategies.external_github_bridge",
        "discover_external_repo_capabilities",
    ),
    "external_strategy_catalog": (
        "hl_observer.strategies.external_github_bridge",
        "external_strategy_catalog",
    ),
    "external_strategy_definitions": (
        "hl_observer.strategies.external_github_bridge",
        "external_strategy_definitions",
    ),
    "register_external_github_profiles": (
        "hl_observer.strategies.external_github_bridge",
        "register_external_github_profiles",
    ),
    "DistilledGithubIdea": (
        "hl_observer.strategies.github_distillation",
        "DistilledGithubIdea",
    ),
    "distillation_status_counts": (
        "hl_observer.strategies.github_distillation",
        "distillation_status_counts",
    ),
    "priority_distillation_matrix": (
        "hl_observer.strategies.github_distillation",
        "priority_distillation_matrix",
    ),
}


def __getattr__(name: str) -> Any:
    """Resolve heavy re-exports lazily to keep package imports cycle-free."""

    target = _LAZY_EXPORTS.get(name)
    if target is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    module_name, attribute = target
    from importlib import import_module

    value = getattr(import_module(module_name), attribute)
    globals()[name] = value
    return value


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
