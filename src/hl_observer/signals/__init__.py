"""Signal normalization, scoring, and decision contracts."""

from hl_observer.signals.cluster_detector import ClusterConfig, SignalCluster, detect_signal_clusters
from hl_observer.signals.leader_delta import (
    ENTRY_ACTIONS,
    LeaderDelta,
    leader_delta_from_lifecycle_event,
)

__all__ = [
    "ClusterConfig",
    "ENTRY_ACTIONS",
    "LeaderDelta",
    "SignalCluster",
    "detect_signal_clusters",
    "leader_delta_from_lifecycle_event",
]
