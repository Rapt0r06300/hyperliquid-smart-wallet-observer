"""Bounded low-latency event queue with event-time ordering."""

from __future__ import annotations

from dataclasses import dataclass
import heapq


@dataclass(frozen=True, slots=True)
class QueuedEvent:
    event_time_ms: int
    event_id: str
    payload: dict[str, object]
    late: bool = False


class LowLatencyEventQueue:
    def __init__(self, *, max_size: int = 1_000, late_after_ms: int = 2_000) -> None:
        self.max_size = int(max_size)
        self.late_after_ms = int(late_after_ms)
        self._heap: list[tuple[int, str, QueuedEvent]] = []
        self.dropped = 0

    def push(self, event: QueuedEvent, *, now_ms: int | None = None) -> None:
        late = bool(now_ms is not None and int(now_ms) - int(event.event_time_ms) > self.late_after_ms)
        queued = QueuedEvent(event.event_time_ms, event.event_id, dict(event.payload), late=late)
        if len(self._heap) >= self.max_size:
            heapq.heappop(self._heap)
            self.dropped += 1
        heapq.heappush(self._heap, (queued.event_time_ms, queued.event_id, queued))

    def pop_ready(self) -> QueuedEvent | None:
        if not self._heap:
            return None
        return heapq.heappop(self._heap)[2]

    def drain(self) -> tuple[QueuedEvent, ...]:
        out = []
        while self._heap:
            out.append(self.pop_ready())
        return tuple(event for event in out if event is not None)


__all__ = ["LowLatencyEventQueue", "QueuedEvent"]
