"""Execution delay helpers for replaying copy decisions."""

from __future__ import annotations

from dataclasses import dataclass
import math


@dataclass(frozen=True, slots=True)
class DelayedEvent:
    event_id: str
    original_ts_ms: int
    effective_ts_ms: int
    delay_ms: int


def apply_execution_delay(event_id: str, ts_ms: int, *, delay_seconds: float) -> DelayedEvent:
    if not isinstance(event_id, str) or not event_id.strip():
        raise ValueError("event_id must be a non-empty string")
    if isinstance(ts_ms, bool) or not isinstance(ts_ms, int) or ts_ms <= 0:
        raise ValueError("ts_ms must be a positive integer")
    if isinstance(delay_seconds, bool):
        raise ValueError("delay_seconds must be a finite non-negative number")
    try:
        delay_value = float(delay_seconds)
    except (TypeError, ValueError, OverflowError) as exc:
        raise ValueError("delay_seconds must be a finite non-negative number") from exc
    if not math.isfinite(delay_value) or delay_value < 0:
        raise ValueError("delay_seconds must be a finite non-negative number")
    delay_ms = int(delay_value * 1000)
    effective_ts_ms = ts_ms + delay_ms
    if effective_ts_ms <= 0 or effective_ts_ms > 9_223_372_036_854_775_807:
        raise ValueError("effective replay timestamp is outside the supported range")
    return DelayedEvent(
        event_id=event_id.strip(),
        original_ts_ms=ts_ms,
        effective_ts_ms=effective_ts_ms,
        delay_ms=delay_ms,
    )


__all__ = ["DelayedEvent", "apply_execution_delay"]
