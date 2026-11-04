"""Replay engine that applies deterministic timestamp ordering and delay."""

from __future__ import annotations

from typing import Iterable

from .execution_delay_model import apply_execution_delay


def replay_events_with_delay(events: Iterable[dict[str, object]], *, delay_seconds: float) -> tuple[dict[str, object], ...]:
    replayed = []
    seen_event_ids: set[str] = set()
    for event in events:
        if not isinstance(event, dict):
            raise ValueError("replay events must be mappings")
        delayed = apply_execution_delay(
            event.get("event_id"),  # type: ignore[arg-type]
            event.get("ts_ms"),  # type: ignore[arg-type]
            delay_seconds=delay_seconds,
        )
        if delayed.event_id in seen_event_ids:
            raise ValueError("replay event_id must be unique")
        seen_event_ids.add(delayed.event_id)
        row = dict(event)
        row["effective_ts_ms"] = delayed.effective_ts_ms
        row["delay_ms"] = delayed.delay_ms
        replayed.append(row)
    # A stable sort alone would preserve whichever input order a platform or
    # upstream merge happened to provide for equal timestamps.  Native event
    # identity is the canonical tie-break, so the same SAFE tape yields the
    # same replay sequence regardless of input permutation.
    return tuple(sorted(
        replayed,
        key=lambda row: (int(row["effective_ts_ms"]), str(row["event_id"]).strip()),
    ))


__all__ = ["replay_events_with_delay"]
