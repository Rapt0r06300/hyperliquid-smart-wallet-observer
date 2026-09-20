"""Causal, source-attributed external-event contract for Event Intelligence.

This module is deliberately network-free and execution-free. It stores only the
structured facts Alina needs for replay/backtest causality; source text is not
required and no trading capability exists here.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Iterable


SCHEMA_VERSION = "alina.external_event.v1"


class ExternalEventType(StrEnum):
    NEWS = "NEWS"
    PREDICTION = "PREDICTION"
    MACRO = "MACRO"
    GEOPOLITICAL = "GEOPOLITICAL"
    SANCTION = "SANCTION"
    CONFLICT = "CONFLICT"
    MILITARY = "MILITARY"
    CYBER = "CYBER"
    INFRASTRUCTURE = "INFRASTRUCTURE"
    SUPPLY_CHAIN = "SUPPLY_CHAIN"
    NATURAL = "NATURAL"
    WEATHER = "WEATHER"
    OUTAGE = "OUTAGE"
    OTHER = "OTHER"


class SourceTier(StrEnum):
    PRIMARY_OFFICIAL = "PRIMARY_OFFICIAL"
    WIRE = "WIRE"
    SPECIALIST = "SPECIALIST"
    OSINT = "OSINT"
    AGGREGATOR = "AGGREGATOR"
    OTHER = "OTHER"


@dataclass(frozen=True, slots=True)
class ExternalEvent:
    """Structured external event whose causal availability is ingest_ts_ms.

    publication_ts_ms describes the source. retrieval_ts_ms describes transport
    into the collector. ingest_ts_ms is the earliest instant Alina may use the
    information in a decision or replay.
    """

    event_id: str
    source: str
    event_type: ExternalEventType
    source_tier: SourceTier
    retrieval_ts_ms: int
    ingest_ts_ms: int
    methodology_version: str
    raw_evidence_ref: str
    publication_ts_ms: int | None = None
    event_ts_ms: int | None = None
    source_link: str = ""
    country_codes: tuple[str, ...] = ()
    regions: tuple[str, ...] = ()
    entities: tuple[str, ...] = ()
    severity: float | None = None
    classification_confidence: float = 1.0
    corroboration_count: int = 1
    real_execution: bool = False

    def __post_init__(self) -> None:
        for field_name in (
            "event_id",
            "source",
            "methodology_version",
            "raw_evidence_ref",
        ):
            if not str(getattr(self, field_name, "")).strip():
                raise ValueError(f"{field_name} is required")
        if not isinstance(self.event_type, ExternalEventType):
            raise TypeError("event_type must be ExternalEventType")
        if not isinstance(self.source_tier, SourceTier):
            raise TypeError("source_tier must be SourceTier")
        for field_name in ("retrieval_ts_ms", "ingest_ts_ms"):
            value = getattr(self, field_name)
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                raise ValueError(f"{field_name} must be a non-negative integer")
        for field_name in ("publication_ts_ms", "event_ts_ms"):
            value = getattr(self, field_name)
            if value is not None and (
                isinstance(value, bool) or not isinstance(value, int) or value < 0
            ):
                raise ValueError(f"{field_name} must be None or a non-negative integer")
        if self.retrieval_ts_ms > self.ingest_ts_ms:
            raise ValueError("retrieval_ts_ms cannot be after ingest_ts_ms")
        if (
            self.publication_ts_ms is not None
            and self.publication_ts_ms > self.retrieval_ts_ms
        ):
            raise ValueError("publication_ts_ms cannot be after retrieval_ts_ms")
        if not 0.0 <= float(self.classification_confidence) <= 1.0:
            raise ValueError("classification_confidence must be in [0, 1]")
        if self.severity is not None and not 0.0 <= float(self.severity) <= 1.0:
            raise ValueError("severity must be in [0, 1]")
        if isinstance(self.corroboration_count, bool) or self.corroboration_count < 1:
            raise ValueError("corroboration_count must be >= 1")
        if self.real_execution is not False:
            raise ValueError("external events are read-only; real_execution must be false")

    @property
    def available_ts_ms(self) -> int:
        """Earliest causal decision timestamp."""

        return self.ingest_ts_ms

    @property
    def dedupe_key(self) -> tuple[str, str]:
        return (self.source, self.event_id)

    def is_available_at(self, decision_ts_ms: int) -> bool:
        return int(decision_ts_ms) >= self.available_ts_ms

    def to_r2_record(self) -> dict[str, object]:
        """Return an archive-friendly structured-event record without source text."""

        return {
            "schema": SCHEMA_VERSION,
            "event_id": self.event_id,
            "source": self.source,
            "event_type": self.event_type.value,
            "source_tier": self.source_tier.value,
            "publication_ts_ms": self.publication_ts_ms,
            "retrieval_ts_ms": self.retrieval_ts_ms,
            "ingest_ts_ms": self.ingest_ts_ms,
            "event_ts_ms": self.event_ts_ms,
            "source_link": self.source_link,
            "country_codes": list(self.country_codes),
            "regions": list(self.regions),
            "entities": list(self.entities),
            "severity": self.severity,
            "classification_confidence": self.classification_confidence,
            "corroboration_count": self.corroboration_count,
            "methodology_version": self.methodology_version,
            "raw_evidence_ref": self.raw_evidence_ref,
            "real_execution": False,
        }


@dataclass(frozen=True, slots=True)
class ExternalEventDecision:
    accepted: bool
    reason: str


class ExternalEventReplayGuard:
    """Fail closed on future information and duplicate source events."""

    def __init__(self, *, seen_keys: Iterable[tuple[str, str]] = ()) -> None:
        self._seen = set(seen_keys)

    def seen_keys(self) -> frozenset[tuple[str, str]]:
        return frozenset(self._seen)

    def observe(
        self,
        event: ExternalEvent,
        *,
        decision_ts_ms: int,
    ) -> ExternalEventDecision:
        if event.dedupe_key in self._seen:
            return ExternalEventDecision(False, "DUPLICATE_EVENT")
        if not event.is_available_at(decision_ts_ms):
            return ExternalEventDecision(False, "FUTURE_INFORMATION")
        self._seen.add(event.dedupe_key)
        return ExternalEventDecision(True, "ACCEPT")


__all__ = [
    "ExternalEvent",
    "ExternalEventDecision",
    "ExternalEventReplayGuard",
    "ExternalEventType",
    "SCHEMA_VERSION",
    "SourceTier",
]
