"""Source registry & provenance (V12 capability A — Fondation). Read-only."""

from hl_observer.sources.clock import ClockSample, ClockSyncState, ClockSynchronizer
from hl_observer.sources.models import (
    FetchProvenance,
    SourceDefinition,
    SourceHealthSnapshot,
    SourceKind,
    SourceStatus,
)
from hl_observer.sources.registry import SourceRegistry

__all__ = [
    "ClockSample",
    "ClockSyncState",
    "ClockSynchronizer",
    "SourceKind",
    "SourceStatus",
    "SourceDefinition",
    "FetchProvenance",
    "SourceHealthSnapshot",
    "SourceRegistry",
]
