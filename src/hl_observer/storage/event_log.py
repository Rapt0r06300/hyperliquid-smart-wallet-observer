"""Event log (V12, repo 05 PolyWeather): monotonic revision + replay missed events.

Append-only log with a monotonically increasing revision per event. A client that missed
events asks `since(last_revision)` to catch up (replay). In-memory + bounded; the same
contract maps onto a SQLite table for persistence. Pure / read-only research bookkeeping.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class LoggedEvent:
    revision: int
    kind: str
    payload: dict
    ts_ms: int


class EventLog:
    def __init__(self, *, max_events: int = 10_000) -> None:
        self._events: deque[LoggedEvent] = deque(maxlen=max(1, int(max_events)))
        self._rev = 0

    def append(self, *, kind: str, payload: dict | None = None, ts_ms: int = 0) -> int:
        self._rev += 1
        self._events.append(LoggedEvent(revision=self._rev, kind=str(kind),
                                        payload=dict(payload or {}), ts_ms=int(ts_ms)))
        return self._rev

    @property
    def latest_revision(self) -> int:
        return self._rev

    def since(self, revision: int) -> list[LoggedEvent]:
        """Events strictly after `revision` (replay of missed events)."""
        r = int(revision)
        return [e for e in self._events if e.revision > r]

    def __len__(self) -> int:
        return len(self._events)


__all__ = ["LoggedEvent", "EventLog"]
