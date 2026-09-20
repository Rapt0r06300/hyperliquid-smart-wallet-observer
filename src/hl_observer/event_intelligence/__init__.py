"""Event Intelligence primitives.

Network adapters are intentionally separate from these pure contracts. The package
contains no order path and all exposed research objects are read-only.
"""

from .external_event import (
    ExternalEvent,
    ExternalEventDecision,
    ExternalEventReplayGuard,
    ExternalEventType,
    SourceTier,
)
from .price_discovery import EventMarketReaction, measure_event_price_discovery

__all__ = [
    "EventMarketReaction",
    "ExternalEvent",
    "ExternalEventDecision",
    "ExternalEventReplayGuard",
    "ExternalEventType",
    "SourceTier",
    "measure_event_price_discovery",
]
