"""Scheduled macro-event clock and surprise features for Event Intelligence."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable


@dataclass(frozen=True, slots=True)
class ScheduledMacroEvent:
    event_id: str
    name: str
    scheduled_ts_ms: int
    source: str
    series_id: str = ""
    expected_value: float | None = None
    actual_value: float | None = None
    unit: str = ""
    released_ts_ms: int | None = None

    @property
    def is_released(self) -> bool:
        return self.released_ts_ms is not None

    @property
    def surprise_score(self) -> float | None:
        if self.expected_value is None or self.actual_value is None:
            return None
        scale = max(abs(float(self.expected_value)), 1e-9)
        return (float(self.actual_value) - float(self.expected_value)) / scale


@dataclass(frozen=True, slots=True)
class MacroWindow:
    event_id: str
    phase: str
    distance_ms: int
    scheduled_ts_ms: int
    released_ts_ms: int | None
    surprise_score: float | None


class MacroEventClock:
    def __init__(self, events: Iterable[ScheduledMacroEvent]) -> None:
        self._events = tuple(sorted(events, key=lambda row: (row.scheduled_ts_ms, row.event_id)))

    def nearest_window(
        self,
        *,
        as_of_ms: int,
        pre_window_ms: int = 300_000,
        post_window_ms: int = 900_000,
    ) -> MacroWindow | None:
        now = int(as_of_ms)
        candidates: list[tuple[int, ScheduledMacroEvent, str]] = []
        for event in self._events:
            delta = now - int(event.scheduled_ts_ms)
            if -int(pre_window_ms) <= delta < 0:
                candidates.append((abs(delta), event, "PRE_EVENT"))
            elif 0 <= delta <= int(post_window_ms):
                phase = "POST_RELEASE" if event.released_ts_ms is not None else "POST_SCHEDULE"
                candidates.append((abs(delta), event, phase))
        if not candidates:
            return None
        _distance, event, phase = min(candidates, key=lambda row: (row[0], row[1].event_id))
        return MacroWindow(
            event_id=event.event_id,
            phase=phase,
            distance_ms=now - int(event.scheduled_ts_ms),
            scheduled_ts_ms=int(event.scheduled_ts_ms),
            released_ts_ms=event.released_ts_ms,
            surprise_score=event.surprise_score,
        )

    def event(self, event_id: str) -> ScheduledMacroEvent | None:
        target = str(event_id)
        return next((row for row in self._events if row.event_id == target), None)


__all__ = [
    "MacroEventClock",
    "MacroWindow",
    "ScheduledMacroEvent",
]
