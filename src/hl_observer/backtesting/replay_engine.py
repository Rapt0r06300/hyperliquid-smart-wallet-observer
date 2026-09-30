"""Replay engine that applies timestamp ordering and delay."""

from __future__ import annotations

from typing import Iterable

from .execution_delay_model import apply_execution_delay


def replay_events_with_delay(events: Iterable[dict[str, object]], *, delay_seconds: float) -> tuple[dict[str, object], ...]:
    replayed = []
    for event in events:
        delayed = apply_execution_delay(str(event.get("event_id") or ""), int(event.get("ts_ms") or 0), delay_seconds=delay_seconds)
        row = dict(event)
        row["effective_ts_ms"] = delayed.effective_ts_ms
        row["delay_ms"] = delayed.delay_ms
        replayed.append(row)
    return tuple(sorted(replayed, key=lambda row: int(row["effective_ts_ms"])))


__all__ = ["replay_events_with_delay"]
