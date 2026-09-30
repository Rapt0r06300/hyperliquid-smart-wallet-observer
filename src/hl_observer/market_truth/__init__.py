"""Causal market-truth pipeline for replay and local paper research."""

from hl_observer.market_truth.executable_replay import (
    ExecutableFill,
    ExecutionCosts,
    ReplayIntent,
    replay_executable_fill,
)
from hl_observer.market_truth.truth_chain import (
    EvidenceRecord,
    TruthChain,
    TruthChainResult,
)
from hl_observer.market_truth.pipeline import (
    MarketTruthPipeline,
    MarketTruthPipelineResult,
)
from hl_observer.market_truth.validation import (
    ResearchVerdict,
    evaluate_research_candidate,
)

__all__ = [
    "EvidenceRecord",
    "ExecutableFill",
    "ExecutionCosts",
    "MarketTruthPipeline",
    "MarketTruthPipelineResult",
    "ReplayIntent",
    "ResearchVerdict",
    "TruthChain",
    "TruthChainResult",
    "evaluate_research_candidate",
    "replay_executable_fill",
]
