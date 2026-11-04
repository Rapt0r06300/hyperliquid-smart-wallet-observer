"""Causal timestamp contract shared by live collection and replay.

Wall-clock timestamps are durable and may be used for freshness after a
restart. Monotonic timestamps are process-local and may only order events
inside the same connection. A persisted age is diagnostic evidence, never a
substitute for recomputing the current age.
"""
from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime, timezone
import math
from typing import Any


def _optional_int(value: Any) -> int | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        numeric = float(value)
        if not math.isfinite(numeric) or numeric != int(numeric):
            return None
        return int(numeric)
    except (TypeError, ValueError, OverflowError):
        return None


def _strict_positive_int(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    try:
        numeric = float(value)
        parsed = int(numeric)
    except (TypeError, ValueError, OverflowError):
        return None
    if not math.isfinite(numeric) or numeric <= 0 or numeric != parsed:
        return None
    return parsed
@dataclass(frozen=True, slots=True)
class CausalTimestamp:
    exchange_ts_ms: int | None
    recv_wall_ts_ms: int | None
    recv_mono_ns: int | None
    write_wall_ts_ms: int | None
    event_id: str | None = None
    connection_id: str | None = None
    sequence: int | None = None
    clock_source: str | None = None

    def __post_init__(self) -> None:
        for name in (
            "exchange_ts_ms",
            "recv_wall_ts_ms",
            "recv_mono_ns",
            "write_wall_ts_ms",
            "sequence",
        ):
            value = getattr(self, name)
            if value is not None and value < 0:
                raise ValueError(f"{name} must be non-negative")
        if (
            self.recv_wall_ts_ms is not None
            and self.write_wall_ts_ms is not None
            and self.write_wall_ts_ms < self.recv_wall_ts_ms
        ):
            raise ValueError("write_wall_ts_ms cannot precede recv_wall_ts_ms")
        if (
            self.exchange_ts_ms is not None
            and self.recv_wall_ts_ms is not None
            and self.exchange_ts_ms > self.recv_wall_ts_ms
        ):
            raise ValueError("exchange_ts_ms cannot exceed recv_wall_ts_ms")

    @property
    def observable_at_ms(self) -> int | None:
        """Earliest durable wall time at which replay may consume the event."""
        if self.write_wall_ts_ms is not None:
            return self.write_wall_ts_ms
        return self.recv_wall_ts_ms

    def current_age_ms(self, *, now_wall_ms: int | float) -> float | None:
        """Return current wall-clock age, never a frozen persisted age."""
        if self.recv_wall_ts_ms is None:
            return None
        return float(now_wall_ms) - float(self.recv_wall_ts_ms)

    def monotonic_order_key(self) -> tuple[str, int, int]:
        """Return a connection-local ordering key.

        The key must not be compared across connections. Callers that need a
        durable order must use ``observable_at_ms`` and stable event identity.
        """
        if self.connection_id is None or self.recv_mono_ns is None:
            raise ValueError("monotonic order requires connection_id and recv_mono_ns")
        return (
            self.connection_id,
            -1 if self.sequence is None else self.sequence,
            self.recv_mono_ns,
        )

    def stable_order_key(self) -> tuple[int, int, int, str]:
        """Return a durable deterministic key for equal wall-clock timestamps."""

        observable = self.observable_at_ms
        if observable is None:
            raise ValueError("missing durable timestamp")
        return (
            observable,
            -1 if self.sequence is None else self.sequence,
            -1 if self.recv_mono_ns is None else self.recv_mono_ns,
            self.event_id or "",
        )


def causal_timestamp_from_record(record: Mapping[str, Any]) -> CausalTimestamp:
    """Read canonical names first and legacy aliases only for compatibility."""
    return CausalTimestamp(
        exchange_ts_ms=_optional_int(record.get("exchange_ts_ms")),
        recv_wall_ts_ms=_optional_int(
            record.get("recv_wall_ts_ms", record.get("received_ts_ms"))
        ),
        recv_mono_ns=_optional_int(
            record.get("recv_mono_ns", record.get("local_monotonic_ns"))
        ),
        write_wall_ts_ms=_optional_int(
            record.get("write_wall_ts_ms", record.get("written_ts_ms"))
        ),
        event_id=(str(record["event_id"]) if record.get("event_id") else None),
        connection_id=(
            str(record["connection_id"]) if record.get("connection_id") else None
        ),
        sequence=_optional_int(record.get("sequence")),
        clock_source=(
            str(
                record.get(
                    "clock_source",
                    record.get("clock_provenance", record.get("time_source")),
                )
            )
            if record.get("clock_source", record.get("clock_provenance", record.get("time_source")))
            else None
        ),
    )


def current_record_age_ms(
    record: Mapping[str, Any],
    *,
    now_wall_ms: int | float,
    wall_keys: tuple[str, ...] = (
        "recv_wall_ts_ms",
        "received_ts_ms",
        "ts_wall_ms",
        "ts_ms",
    ),
) -> float | None:
    """Recompute age from a durable wall timestamp.

    ``age_ms`` and related persisted fields are deliberately ignored.
    Missing timestamps remain missing instead of silently becoming ``now``.
    """
    for key in wall_keys:
        value = _optional_int(record.get(key))
        if value is not None:
            return float(now_wall_ms) - float(value)
    return None


def causal_clock_skew_ms(
    *, exchange_ts_ms: Any, receive_ts_ms: Any
) -> float | None:
    """Return measured exchange-to-receive skew; missing evidence stays missing."""

    exchange = _strict_positive_int(exchange_ts_ms)
    receive = _strict_positive_int(receive_ts_ms)
    if exchange is None or receive is None:
        return None
    return float(receive - exchange)


def causal_event_admission(
    *,
    event_ts_ms: Any,
    receive_ts_ms: Any,
    decision_ts_ms: Any,
    feature_cutoff_ts_ms: Any | None = None,
    max_age_ms: Any | None = None,
) -> dict[str, Any]:
    """Admit only observations that were available before the decision/cutoff."""

    event = _strict_positive_int(event_ts_ms)
    receive = _strict_positive_int(receive_ts_ms)
    decision = _strict_positive_int(decision_ts_ms)
    cutoff = (
        _strict_positive_int(feature_cutoff_ts_ms)
        if feature_cutoff_ts_ms is not None
        else None
    )
    max_age = _strict_positive_int(max_age_ms) if max_age_ms is not None else None
    if event is None or receive is None or decision is None or (
        feature_cutoff_ts_ms is not None and cutoff is None
    ) or (max_age_ms is not None and max_age is None):
        return {"status": "UNMEASURABLE", "reason": "CAUSAL_CLOCK_MISSING", "real_execution": False}
    if event > receive:
        return {"status": "UNMEASURABLE", "reason": "EVENT_AFTER_RECEIVE", "real_execution": False}
    if event > decision or receive > decision:
        return {"status": "NO_TRADE", "reason": "EVENT_AFTER_DECISION", "real_execution": False}
    if cutoff is not None and (event > cutoff or receive > cutoff):
        return {"status": "NO_TRADE", "reason": "EVENT_AFTER_CUTOFF", "real_execution": False}
    if max_age is not None and receive - event > max_age:
        return {"status": "NO_TRADE", "reason": "RECEIVE_LATENCY_EXCEEDED", "real_execution": False}
    return {
        "status": "PROVEN",
        "event_ts_ms": event,
        "receive_ts_ms": receive,
        "decision_ts_ms": decision,
        "feature_cutoff_ts_ms": cutoff,
        "real_execution": False,
    }


def parse_utc_epoch_ms(value: Any) -> int | None:
    """Parse an ISO timestamp only when it carries an explicit UTC offset."""

    if not isinstance(value, str) or not value.strip():
        return None
    try:
        parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        return None
    return int(parsed.astimezone(timezone.utc).timestamp() * 1000)


def bounded_asof_match(
    *, event_ts_ms: Any, candidate_ts_ms: Any, tolerance_ms: Any
) -> dict[str, Any]:
    """Match only a candidate at-or-before an event within a finite tolerance."""

    event = _strict_positive_int(event_ts_ms)
    candidate = _strict_positive_int(candidate_ts_ms)
    tolerance = _strict_positive_int(tolerance_ms)
    if event is None or candidate is None or tolerance is None:
        return {"status": "UNMEASURABLE", "reason": "ASOF_CLOCK_MISSING", "real_execution": False}
    if candidate > event:
        return {"status": "NO_TRADE", "reason": "CANDIDATE_AFTER_EVENT", "real_execution": False}
    age = event - candidate
    if age > tolerance:
        return {"status": "NO_TRADE", "reason": "ASOF_TOLERANCE_EXCEEDED", "age_ms": age, "real_execution": False}
    return {"status": "PROVEN", "age_ms": age, "real_execution": False}


def compare_monotonic_within_connection(
    left: CausalTimestamp,
    right: CausalTimestamp,
) -> int:
    """Compare process-local clocks only when their connection is identical."""
    if not left.connection_id or left.connection_id != right.connection_id:
        raise ValueError("monotonic timestamps cannot be compared across connections")
    if left.recv_mono_ns is None or right.recv_mono_ns is None:
        raise ValueError("missing monotonic timestamp")
    return (left.recv_mono_ns > right.recv_mono_ns) - (
        left.recv_mono_ns < right.recv_mono_ns
    )


__all__ = [
    "CausalTimestamp",
    "bounded_asof_match",
    "causal_clock_skew_ms",
    "causal_event_admission",
    "causal_timestamp_from_record",
    "compare_monotonic_within_connection",
    "current_record_age_ms",
    "parse_utc_epoch_ms",
]
