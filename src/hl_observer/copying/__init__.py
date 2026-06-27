"""Dry-run copy research pipeline.

Batch 1 intentionally stops at paper/mock-USDC candidate analysis. It never
places real orders and never unlocks testnet execution.
"""

from .simulation_pipeline import (
    PaperSimulationDecision,
    build_risk_context_from_signal,
    run_paper_simulation_decision,
)
from .runtime_v9_adapter import (
    RuntimeV9DecisionSummary,
    attach_v9_runtime_diagnostics,
    build_signal_candidate_from_event,
)

__all__ = [
    "PaperSimulationDecision",
    "RuntimeV9DecisionSummary",
    "attach_v9_runtime_diagnostics",
    "build_risk_context_from_signal",
    "build_signal_candidate_from_event",
    "run_paper_simulation_decision",
]
