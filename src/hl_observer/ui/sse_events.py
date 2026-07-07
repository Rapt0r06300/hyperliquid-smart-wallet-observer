"""SSE events (V12, repo 05): format an event log as Server-Sent Events (read-only).

Pure formatting over an EventLog: each SSE frame carries the revision as the `id:` so a
reconnecting client resumes with Last-Event-ID and replays only what it missed.
"""

from __future__ import annotations

import json

from hl_observer.storage.event_log import EventLog, LoggedEvent


def format_sse(event: LoggedEvent) -> str:
    data = json.dumps({"kind": event.kind, "payload": event.payload, "ts_ms": event.ts_ms},
                      sort_keys=True, default=str)
    return f"id: {event.revision}\nevent: {event.kind}\ndata: {data}\n\n"


def stream_since(log: EventLog, last_event_id: int) -> list[str]:
    """SSE frames for everything the client missed since last_event_id."""
    return [format_sse(e) for e in log.since(last_event_id)]


__all__ = ["format_sse", "stream_since"]
