"""Local-first efficiency primitives for bounded, auditable agent work.

These helpers optimize repository navigation and verification only.  They do not
submit orders, call external services, or turn an unknown result into success.
"""

from .context_bundle import ContextBundle, ContextRequest, compile_context
from .experience_memory import ExperienceRecord, ExperienceStore
from .loop_guard import LoopDecision, LoopGuard, should_rerun_test
from .model_routing import ExecutionTier, RoutingDecision, route_task
from .output_compactor import CompactionResult, compact_output
from .parallel_reads import ReadResult, read_many
from .prompt_cache import StablePrefix, build_cache_key, build_stable_prefix
from .repo_index import FileRecord, RepoIndex, build_incremental_index, load_index
from .telemetry import EfficiencyReceipt, estimate_tokens
from .test_impact import TestImpactPlan, select_impacted_tests

__all__ = [
    "CompactionResult",
    "ContextBundle",
    "ContextRequest",
    "EfficiencyReceipt",
    "ExecutionTier",
    "ExperienceRecord",
    "ExperienceStore",
    "FileRecord",
    "LoopDecision",
    "LoopGuard",
    "ReadResult",
    "RepoIndex",
    "RoutingDecision",
    "StablePrefix",
    "TestImpactPlan",
    "build_cache_key",
    "build_incremental_index",
    "build_stable_prefix",
    "compact_output",
    "compile_context",
    "estimate_tokens",
    "load_index",
    "read_many",
    "route_task",
    "select_impacted_tests",
    "should_rerun_test",
]
