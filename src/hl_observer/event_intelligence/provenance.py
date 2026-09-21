"""Provenance, independent-source clustering and triangulation for Event Intelligence."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from hl_observer.event_intelligence.external_event import ExternalEvent, SourceTier


_TIER_WEIGHT = {
    SourceTier.PRIMARY_OFFICIAL: 1.00,
    SourceTier.WIRE: 0.95,
    SourceTier.SPECIALIST: 0.85,
    SourceTier.OSINT: 0.65,
    SourceTier.AGGREGATOR: 0.55,
    SourceTier.OTHER: 0.40,
}


@dataclass(frozen=True, slots=True)
class ProvenanceScore:
    score: float
    independent_sources: int
    source_tiers: tuple[str, ...]
    triangulated: bool
    earliest_ingest_ts_ms: int
    latest_ingest_ts_ms: int
    corroboration_latency_ms: int


@dataclass(frozen=True, slots=True)
class EventCluster:
    cluster_id: str
    event_type: str
    event_ids: tuple[str, ...]
    sources: tuple[str, ...]
    source_tiers: tuple[str, ...]
    entities: tuple[str, ...]
    regions: tuple[str, ...]
    earliest_ingest_ts_ms: int
    latest_ingest_ts_ms: int
    provenance: ProvenanceScore


def score_provenance(events: Iterable[ExternalEvent]) -> ProvenanceScore:
    rows = tuple(events)
    if not rows:
        raise ValueError("at least one event is required")
    unique_by_source: dict[str, ExternalEvent] = {}
    for event in sorted(rows, key=lambda row: (row.ingest_ts_ms, row.source, row.event_id)):
        unique_by_source.setdefault(event.source, event)

    independent = tuple(unique_by_source.values())
    weights = [_TIER_WEIGHT.get(row.source_tier, 0.40) for row in independent]
    tiers = tuple(sorted({row.source_tier.value for row in independent}))
    earliest = min(row.ingest_ts_ms for row in independent)
    latest = max(row.ingest_ts_ms for row in independent)
    count_bonus = min(0.20, 0.05 * max(0, len(independent) - 1))
    corroboration_bonus = min(
        0.15,
        0.025 * sum(max(0, row.corroboration_count - 1) for row in independent),
    )
    confidence = sum(float(row.classification_confidence) for row in independent) / len(independent)
    base = max(weights) * 0.55 + (sum(weights) / len(weights)) * 0.25
    score = min(1.0, base + count_bonus + corroboration_bonus) * confidence
    tier_set = {row.source_tier for row in independent}
    triangulated = (
        len(independent) >= 2
        and (
            SourceTier.PRIMARY_OFFICIAL in tier_set
            or SourceTier.WIRE in tier_set
        )
        and len(tier_set) >= 2
    )
    return ProvenanceScore(
        score=round(max(0.0, min(1.0, score)), 6),
        independent_sources=len(independent),
        source_tiers=tiers,
        triangulated=triangulated,
        earliest_ingest_ts_ms=earliest,
        latest_ingest_ts_ms=latest,
        corroboration_latency_ms=latest - earliest,
    )


def cluster_external_events(
    events: Iterable[ExternalEvent],
    *,
    time_bucket_ms: int = 300_000,
) -> tuple[EventCluster, ...]:
    """Deterministic cross-source cluster using type/entities/regions/time bucket."""

    bucket = max(1, int(time_bucket_ms))
    groups: dict[tuple[object, ...], list[ExternalEvent]] = {}
    for event in events:
        entities = tuple(sorted({str(value).strip().upper() for value in event.entities if str(value).strip()}))
        regions = tuple(sorted({str(value).strip().casefold() for value in event.regions if str(value).strip()}))
        key = (
            event.event_type.value,
            entities,
            regions,
            int(event.available_ts_ms) // bucket,
        )
        groups.setdefault(key, []).append(event)

    output: list[EventCluster] = []
    for key, rows in sorted(groups.items(), key=lambda item: str(item[0])):
        provenance = score_provenance(rows)
        event_ids = tuple(sorted({row.event_id for row in rows}))
        sources = tuple(sorted({row.source for row in rows}))
        source_tiers = tuple(sorted({row.source_tier.value for row in rows}))
        entities = tuple(sorted({value for row in rows for value in row.entities}))
        regions = tuple(sorted({value for row in rows for value in row.regions}))
        cluster_id = "|".join(
            (
                str(key[0]),
                str(key[3]),
                ",".join(str(value) for value in key[1]),
                ",".join(str(value) for value in key[2]),
            )
        )
        output.append(
            EventCluster(
                cluster_id=cluster_id,
                event_type=str(key[0]),
                event_ids=event_ids,
                sources=sources,
                source_tiers=source_tiers,
                entities=entities,
                regions=regions,
                earliest_ingest_ts_ms=provenance.earliest_ingest_ts_ms,
                latest_ingest_ts_ms=provenance.latest_ingest_ts_ms,
                provenance=provenance,
            )
        )
    return tuple(output)


__all__ = [
    "EventCluster",
    "ProvenanceScore",
    "cluster_external_events",
    "score_provenance",
]
