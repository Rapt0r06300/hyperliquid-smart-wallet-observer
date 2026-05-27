from __future__ import annotations

from hyper_smart_observer.realtime_monitor.dedupe import EventDedupe
from hyper_smart_observer.realtime_monitor.stream_models import StreamEvent


class EventRouter:
    def __init__(self) -> None:
        self.dedupe = EventDedupe()
        self.events: list[StreamEvent] = []

    def route(self, event: StreamEvent) -> bool:
        if self.dedupe.is_duplicate(event.event_id):
            return False
        self.events.append(event)
        return True
