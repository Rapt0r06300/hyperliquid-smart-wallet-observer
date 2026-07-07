"""Loop-engineering layer for read-only observation and locked testnet flow."""

from hl_observer.loops.candidate_factory import (
    CandidateFactoryReport,
    CandidateFactorySkip,
    build_signal_candidates_from_observation,
    build_signal_candidates_from_position_deltas,
)
from hl_observer.loops.dashboard_payload import build_loop_dashboard_payload
from hl_observer.loops.decision_trace import LoopDecisionTrace, build_decision_traces, traces_to_dicts
from hl_observer.loops.engine import LoopEngineeringRunner
from hl_observer.loops.input_diagnostics import build_loop_input_diagnostics, write_loop_input_diagnostics
from hl_observer.loops.memory import LoopMemoryStore, default_loop_memory_dir
from hl_observer.loops.models import (
    ExecutionFeedback,
    LearningSummary,
    LoopRunResult,
    ResearchThesis,
)

__all__ = [
    "CandidateFactoryReport",
    "CandidateFactorySkip",
    "ExecutionFeedback",
    "LearningSummary",
    "LoopDecisionTrace",
    "LoopEngineeringRunner",
    "LoopMemoryStore",
    "LoopRunResult",
    "ResearchThesis",
    "build_decision_traces",
    "build_loop_dashboard_payload",
    "build_loop_input_diagnostics",
    "build_signal_candidates_from_observation",
    "build_signal_candidates_from_position_deltas",
    "default_loop_memory_dir",
    "traces_to_dicts",
    "write_loop_input_diagnostics",
]
