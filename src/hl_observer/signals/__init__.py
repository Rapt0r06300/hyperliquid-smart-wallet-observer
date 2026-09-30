"""Signal normalization, scoring, and decision contracts."""

from hl_observer.signals.cluster_detector import ClusterConfig, SignalCluster, detect_signal_clusters
from hl_observer.signals.copy_conflict_resolver import CopyConflictDecision, resolve_copy_conflicts
from hl_observer.signals.distilled_opportunity_detector import (
    DistilledOpportunity,
    DistilledOpportunityConfig,
    DistilledOpportunityReport,
    DistilledSignalCandidate,
    detect_distilled_opportunities,
)
from hl_observer.signals.leader_delta import (
    ENTRY_ACTIONS,
    LeaderDelta,
    leader_delta_from_lifecycle_event,
)

__all__ = [
    "ClusterConfig",
    "CopyConflictDecision",
    "DistilledOpportunity",
    "DistilledOpportunityConfig",
    "DistilledOpportunityReport",
    "DistilledSignalCandidate",
    "ENTRY_ACTIONS",
    "LeaderDelta",
    "SignalCluster",
    "detect_signal_clusters",
    "detect_distilled_opportunities",
    "leader_delta_from_lifecycle_event",
    "resolve_copy_conflicts",
]
