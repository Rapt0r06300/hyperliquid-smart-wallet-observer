"""Versioned source catalog and evidence-bound classification policy.

This module keeps source provenance, roles, and licensing-review metadata explicit.
It also prevents model-generated classifications from entering the pipeline without
source evidence and a methodology version.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from hl_observer.event_intelligence.direct_sources import DIRECT_SOURCES
from hl_observer.event_intelligence.external_event import SourceTier


@dataclass(frozen=True, slots=True)
class SourceDescriptor:
    source_id: str
    role: str
    source_tier: SourceTier
    access_mode: str
    primary: bool
    enabled_by_default: bool
    refresh_hint_s: int | None
    license_policy: str
    attribution: str
    machine_access: bool = True
    read_only: bool = True


@dataclass(frozen=True, slots=True)
class SourceCatalogSnapshot:
    version: str
    sources: tuple[SourceDescriptor, ...]

    @property
    def source_ids(self) -> tuple[str, ...]:
        return tuple(row.source_id for row in self.sources)

    def get(self, source_id: str) -> SourceDescriptor | None:
        target = str(source_id)
        return next((row for row in self.sources if row.source_id == target), None)

    def enabled(self) -> tuple[SourceDescriptor, ...]:
        return tuple(row for row in self.sources if row.enabled_by_default)


@dataclass(frozen=True, slots=True)
class ClassificationEnvelope:
    label: str
    confidence: float
    methodology_version: str
    evidence_refs: tuple[str, ...]
    model_id: str = ""

    def __post_init__(self) -> None:
        if not str(self.label).strip():
            raise ValueError("classification label is required")
        if not 0.0 <= float(self.confidence) <= 1.0:
            raise ValueError("classification confidence must be in [0,1]")
        if not str(self.methodology_version).strip():
            raise ValueError("methodology_version is required")
        if not self.evidence_refs or any(not str(ref).strip() for ref in self.evidence_refs):
            raise ValueError("classification requires source evidence refs")


_WORLD_MONITOR = (
    SourceDescriptor(
        source_id="worldmonitor.cross_source",
        role="corroboration_and_cross_domain_signal",
        source_tier=SourceTier.AGGREGATOR,
        access_mode="hosted_api_or_self_host",
        primary=False,
        enabled_by_default=False,
        refresh_hint_s=None,
        license_policy="WORLD_MONITOR_API_EULA_AND_CODE_LICENSE_REVIEW_REQUIRED",
        attribution="World Monitor",
    ),
    SourceDescriptor(
        source_id="worldmonitor.news",
        role="structured_news_metadata",
        source_tier=SourceTier.AGGREGATOR,
        access_mode="hosted_api_or_self_host",
        primary=False,
        enabled_by_default=False,
        refresh_hint_s=None,
        license_policy="WORLD_MONITOR_API_EULA_AND_CODE_LICENSE_REVIEW_REQUIRED",
        attribution="World Monitor",
    ),
    SourceDescriptor(
        source_id="worldmonitor.prediction",
        role="prediction_market_aggregation_read_only",
        source_tier=SourceTier.AGGREGATOR,
        access_mode="hosted_api_or_self_host",
        primary=False,
        enabled_by_default=False,
        refresh_hint_s=None,
        license_policy="WORLD_MONITOR_API_EULA_AND_UPSTREAM_TERMS_REVIEW_REQUIRED",
        attribution="World Monitor",
    ),
)


def build_source_catalog(
    *,
    version: str = "event-intelligence-sources-v1",
    extra_sources: Iterable[SourceDescriptor] = (),
) -> SourceCatalogSnapshot:
    rows: list[SourceDescriptor] = list(_WORLD_MONITOR)
    for spec in DIRECT_SOURCES.values():
        rows.append(
            SourceDescriptor(
                source_id=spec.source_id,
                role="direct_primary_timing" if spec.source_tier == SourceTier.PRIMARY_OFFICIAL else "direct_aggregator_timing",
                source_tier=spec.source_tier,
                access_mode="direct_api",
                primary=spec.source_tier == SourceTier.PRIMARY_OFFICIAL,
                enabled_by_default=bool(spec.enabled_by_default),
                refresh_hint_s=spec.refresh_hint_s,
                license_policy="UPSTREAM_TERMS_AND_ATTRIBUTION_REVIEW_REQUIRED",
                attribution=spec.attribution,
            )
        )
    rows.extend(extra_sources)
    deduped: dict[str, SourceDescriptor] = {}
    for row in rows:
        if row.source_id in deduped:
            raise ValueError(f"duplicate source_id: {row.source_id}")
        deduped[row.source_id] = row
    return SourceCatalogSnapshot(
        version=str(version),
        sources=tuple(deduped[key] for key in sorted(deduped)),
    )


def source_pair_role(
    primary: SourceDescriptor,
    aggregator: SourceDescriptor,
) -> str:
    if not primary.primary:
        raise ValueError("first source must be primary")
    if aggregator.primary:
        raise ValueError("second source must be aggregator/corroboration source")
    return "PRIMARY_SPEED_PLUS_AGGREGATOR_CORROBORATION"


__all__ = [
    "ClassificationEnvelope",
    "SourceCatalogSnapshot",
    "SourceDescriptor",
    "build_source_catalog",
    "source_pair_role",
]
