"""V5 §6: canonical event contract shared by replay and forward read-only feeds."""
from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Iterable


class EventType(StrEnum):
    BBO_SNAPSHOT = "BBO_SNAPSHOT"
    L2_SNAPSHOT = "L2_SNAPSHOT"
    TRADE = "TRADE"
    USER_FILL = "USER_FILL"
    INITIAL_WS_SNAPSHOT = "INITIAL_WS_SNAPSHOT"
    DELTA_UPDATE = "DELTA_UPDATE"


@dataclass(frozen=True, slots=True)
class UnifiedEvent:
    source: str
    venue: str
    symbol_canonical: str
    event_type: EventType
    exchange_ts_ms: int
    recv_wall_ts_ms: int
    recv_mono_ns: int
    write_wall_ts_ms: int
    event_id: str
    connection_id: str
    sequence: int
    schema_version: str
    raw_evidence_ref: str

    def __post_init__(self) -> None:
        for field_name in (
            "source",
            "venue",
            "symbol_canonical",
            "event_id",
            "connection_id",
            "schema_version",
            "raw_evidence_ref",
        ):
            if not str(getattr(self, field_name, "")).strip():
                raise ValueError(f"{field_name} is required")
        if not isinstance(self.event_type, EventType):
            raise TypeError("event_type must be EventType")
        for field_name in (
            "exchange_ts_ms",
            "recv_wall_ts_ms",
            "recv_mono_ns",
            "write_wall_ts_ms",
            "sequence",
        ):
            value = getattr(self, field_name)
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                raise ValueError(f"{field_name} must be a non-negative integer")

    @property
    def is_snapshot(self) -> bool:
        return self.event_type in {
            EventType.BBO_SNAPSHOT,
            EventType.L2_SNAPSHOT,
            EventType.INITIAL_WS_SNAPSHOT,
        }

    @property
    def can_create_economic_delta(self) -> bool:
        return not self.is_snapshot

    @property
    def dedupe_key(self) -> tuple[str, str, str]:
        # Connection changes on reconnect. Event identity must not.
        return (self.source, self.venue, self.event_id)


@dataclass(frozen=True, slots=True)
class ReplayDecision:
    accepted: bool
    reason: str
    sequence_gap: bool = False
    out_of_order: bool = False


class EventReplayGuard:
    """Fail-closed idempotence/sequence guard with resumable seen keys."""

    def __init__(self, *, seen_keys: Iterable[tuple[str, str, str]] = ()) -> None:
        self._seen = set(seen_keys)
        self._last_sequence_by_connection: dict[str, int] = {}

    def seen_keys(self) -> frozenset[tuple[str, str, str]]:
        return frozenset(self._seen)

    def observe(self, event: UnifiedEvent) -> ReplayDecision:
        if event.dedupe_key in self._seen:
            return ReplayDecision(False, "DUPLICATE_EVENT")

        previous = self._last_sequence_by_connection.get(event.connection_id)
        gap = previous is not None and event.sequence > previous + 1
        out_of_order = previous is not None and event.sequence <= previous
        if out_of_order:
            return ReplayDecision(False, "OUT_OF_ORDER", out_of_order=True)
        if gap:
            # Do not advance state or consume the event before reconciliation.
            return ReplayDecision(
                False,
                "SEQUENCE_GAP_RECONCILE_REQUIRED",
                sequence_gap=True,
            )

        self._seen.add(event.dedupe_key)
        self._last_sequence_by_connection[event.connection_id] = event.sequence
        return ReplayDecision(True, "ACCEPT")


__all__ = ["EventReplayGuard", "EventType", "ReplayDecision", "UnifiedEvent"]
