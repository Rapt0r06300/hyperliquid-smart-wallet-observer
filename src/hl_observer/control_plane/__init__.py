"""Fail-closed typed control plane.

Natural-language output is never accepted by this package.  Only bounded
mapping objects that satisfy an allowlisted event contract can reach a
controller or writer.
"""

from hl_observer.control_plane.typed_events import (
    CONTROL_EVENT_SCHEMA,
    ControlEventError,
    ControlEventReplayLedger,
    TypedControlEvent,
    build_typed_control_event,
    validate_typed_control_event,
)

__all__ = [
    "CONTROL_EVENT_SCHEMA",
    "ControlEventError",
    "ControlEventReplayLedger",
    "TypedControlEvent",
    "build_typed_control_event",
    "validate_typed_control_event",
]
