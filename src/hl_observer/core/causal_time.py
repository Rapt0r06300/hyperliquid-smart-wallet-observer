"""Causal timestamp contract shared by live collection and replay.

Wall-clock timestamps are durable and may be used for freshness after a
restart. Monotonic timestamps are process-local and may only order events
inside the same connection. A persisted age is diagnostic evidence, never a
substitute for recomputing the current age.
"""
from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any


def _optional_int(value: Any) -> int | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        return int(float(value))
    except (TypeError, ValueError, OverflowError):
        return None


@dataclass(frozen=True, slots=True)
class CausalTimestamp:
    exchange_ts_ms: int | None
    recv_wall_ts_ms: int | None
    recv_mono_ns: int | None
    write_wall_ts_ms: int | None
    event_id: str | None = None
    connection_id: str | None = None
    sequence: int | None = None

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
    "causal_timestamp_from_record",
    "compare_monotonic_within_connection",
    "current_record_age_ms",
]
