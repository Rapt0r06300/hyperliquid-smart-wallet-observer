"""Phase 10: unified read-only WebSocket resilience façade.

Composes the existing primitives (reconnect backoff, item dedupe, heartbeat
staleness) into ONE supervisor the runtime can adopt as a single entry point.
Pure decisions only — no socket, no network, no order. Caps user-specific
streams at the Hyperliquid limit of 10.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from hyper_smart_observer.realtime_monitor.dedupe import EventDedupe
from hyper_smart_observer.realtime_monitor.heartbeat import heartbeat_stale
from hyper_smart_observer.realtime_monitor.reconnect import backoff_seconds

HYPERLIQUID_MAX_USER_STREAMS = 10


@dataclass
class WsSupervisor:
    heartbeat_max_age_s: int = 30
    max_user_streams: int = HYPERLIQUID_MAX_USER_STREAMS
    reconnect_attempt: int = 0
    last_seen: datetime | None = None
    dedupe: EventDedupe = field(default_factory=EventDedupe)

    def accept_message(self, message: dict[str, Any]) -> bool:
        """Accept a WS message iff it carries at least one unseen item.
        Snapshot re-delivered on reconnect is deduped (no duplicate events)."""
        accepted = self.dedupe.accept_hyperliquid_message(message)
        if accepted:
            self.last_seen = datetime.now(timezone.utc)
            self.reconnect_attempt = 0
        return accepted

    def next_reconnect_delay(self) -> float:
        """Bounded exponential backoff (seconds) for the next reconnect attempt."""
        self.reconnect_attempt += 1
        return backoff_seconds(self.reconnect_attempt)

    def should_fallback_to_rest(self, *, now: datetime | None = None) -> bool:
        """True when the WS heartbeat is stale (or never seen) -> REST reconcile."""
        return heartbeat_stale(self.last_seen, max_age_seconds=self.heartbeat_max_age_s)

    def clamp_user_streams(self, wallets: list[str]) -> list[str]:
        """Never subscribe to more than 10 unique user-specific streams."""
        cap = max(0, min(HYPERLIQUID_MAX_USER_STREAMS, self.max_user_streams))
        return list(wallets)[:cap]
