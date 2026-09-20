"""Event Intelligence primitives.

Network adapters are intentionally separate from pure contracts. All exposed
research objects are read-only and no order path exists in this package.
"""

from .archive import ArchiveAppendResult, EventArchiveCorruptError, EventIntelligenceArchive
from .external_event import (
    ExternalEvent,
    ExternalEventDecision,
    ExternalEventReplayGuard,
    ExternalEventType,
    SourceTier,
)
from .features import (
    NewsFlowFeatures,
    NewsVelocitySignal,
    compute_news_flow_features,
    compute_news_velocity_zscore,
)
from .health import evaluate_worldmonitor_health
from .price_discovery import EventMarketReaction, measure_event_price_discovery
from .worldmonitor import (
    PredictionShiftTracker,
    WorldMonitorAuthRequired,
    WorldMonitorEvent,
    WorldMonitorHTTPError,
    WorldMonitorReadOnlyClient,
    normalize_cross_source_signals,
    normalize_news_digest,
)

__all__ = [
    "ArchiveAppendResult",
    "EventArchiveCorruptError",
    "EventIntelligenceArchive",
    "EventMarketReaction",
    "ExternalEvent",
    "ExternalEventDecision",
    "ExternalEventReplayGuard",
    "ExternalEventType",
    "NewsFlowFeatures",
    "NewsVelocitySignal",
    "PredictionShiftTracker",
    "SourceTier",
    "WorldMonitorAuthRequired",
    "WorldMonitorEvent",
    "WorldMonitorHTTPError",
    "WorldMonitorReadOnlyClient",
    "compute_news_flow_features",
    "compute_news_velocity_zscore",
    "evaluate_worldmonitor_health",
    "measure_event_price_discovery",
    "normalize_cross_source_signals",
    "normalize_news_digest",
]
