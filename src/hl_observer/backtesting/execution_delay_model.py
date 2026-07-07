"""Execution delay helpers for replaying copy decisions."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class DelayedEvent:
    event_id: str
    original_ts_ms: int
    effective_ts_ms: int
    delay_ms: int


def apply_execution_delay(event_id: str, ts_ms: int, *, delay_seconds: float) -> DelayedEvent:
    delay_ms = int(float(delay_seconds) * 1000)
    return DelayedEvent(event_id=str(event_id), original_ts_ms=int(ts_ms), effective_ts_ms=int(ts_ms) + delay_ms, delay_ms=delay_ms)


__all__ = ["DelayedEvent", "apply_execution_delay"]
