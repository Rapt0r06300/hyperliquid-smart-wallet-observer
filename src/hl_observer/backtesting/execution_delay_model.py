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


def requote_during_delay_receipt(*, side: str, reference_price: object, delayed_price: object) -> dict[str, object]:
    """Measure a requote between decision and delayed execution from observed prices."""

    if str(side).upper() not in {"BUY", "SELL"}:
        return {"status": "UNMEASURABLE", "reason": "SIDE_INVALID"}
    try:
        reference, delayed = float(reference_price), float(delayed_price)
    except (TypeError, ValueError, OverflowError):
        return {"status": "UNMEASURABLE", "reason": "PRICE_INVALID"}
    if not all(math.isfinite(value) and value > 0.0 for value in (reference, delayed)):
        return {"status": "UNMEASURABLE", "reason": "PRICE_INVALID"}
    signed_bps = (delayed - reference) / reference * 10_000.0
    adverse_bps = signed_bps if str(side).upper() == "BUY" else -signed_bps
    return {"status": "PROVEN", "requote_bps": round(signed_bps, 8), "adverse_bps": round(max(0.0, adverse_bps), 8)}


__all__ = ["DelayedEvent", "apply_execution_delay", "requote_during_delay_receipt"]
