"""Causal quantitative features derived from structured Event Intelligence observations."""

from __future__ import annotations

import math
import statistics
from dataclasses import dataclass
from typing import Iterable

from hl_observer.event_intelligence.worldmonitor import WorldMonitorEvent


@dataclass(frozen=True, slots=True)
class NewsFlowFeatures:
    as_of_ms: int
    window_ms: int
    event_count: int
    unique_publishers: int
    source_diversity_ratio: float
    corroborated_events: int
    breaking_events: int
    alert_events: int
    velocity_per_min: float
    corroborated_velocity_per_min: float
    mean_importance_score: float | None
    mean_credibility_score: float | None
    max_corroboration_count: int


@dataclass(frozen=True, slots=True)
class NewsVelocitySignal:
    status: str
    as_of_ms: int
    short_window_ms: int
    baseline_window_ms: int
    current_count: int
    current_velocity_per_min: float
    baseline_bucket_count: int
    baseline_mean_count: float | None
    baseline_std_count: float | None
    zscore: float | None


def compute_news_flow_features(
    events: Iterable[WorldMonitorEvent],
    *,
    as_of_ms: int,
    window_ms: int = 300_000,
) -> NewsFlowFeatures:
    """Summarize fresh news observations using Alina ingest timestamps only."""

    if int(window_ms) <= 0:
        raise ValueError("window_ms must be > 0")
    rows = _deduped_news(
        events,
        start_ms=int(as_of_ms) - int(window_ms),
        end_ms=int(as_of_ms),
    )
    count = len(rows)
    publishers = {row.publisher.casefold() for row in rows if row.publisher.strip()}
    importance = [
        float(row.importance_score)
        for row in rows
        if row.importance_score is not None and math.isfinite(float(row.importance_score))
    ]
    credibility = [
        float(row.credibility_score)
        for row in rows
        if row.credibility_score is not None and math.isfinite(float(row.credibility_score))
    ]
    corroborated = sum(row.event.corroboration_count >= 2 for row in rows)
    breaking = sum(row.story_phase.upper().endswith("_BREAKING") for row in rows)
    alerts = sum(row.is_alert for row in rows)
    source_weight = sum(max(1, row.source_count, row.event.corroboration_count) for row in rows)
    minutes = float(window_ms) / 60_000.0
    return NewsFlowFeatures(
        as_of_ms=int(as_of_ms),
        window_ms=int(window_ms),
        event_count=count,
        unique_publishers=len(publishers),
        source_diversity_ratio=(len(publishers) / count if count else 0.0),
        corroborated_events=corroborated,
        breaking_events=breaking,
        alert_events=alerts,
        velocity_per_min=(count / minutes),
        corroborated_velocity_per_min=(source_weight / minutes),
        mean_importance_score=(statistics.fmean(importance) if importance else None),
        mean_credibility_score=(statistics.fmean(credibility) if credibility else None),
        max_corroboration_count=max(
            (row.event.corroboration_count for row in rows),
            default=0,
        ),
    )


def compute_news_velocity_zscore(
    events: Iterable[WorldMonitorEvent],
    *,
    as_of_ms: int,
    short_window_ms: int = 300_000,
    baseline_window_ms: int = 86_400_000,
    minimum_baseline_buckets: int = 8,
) -> NewsVelocitySignal:
    """Compare current unique news count with prior equal-duration causal buckets."""

    short = int(short_window_ms)
    baseline = int(baseline_window_ms)
    if short <= 0 or baseline < short:
        raise ValueError("invalid velocity windows")
    bucket_count = baseline // short
    if bucket_count < int(minimum_baseline_buckets):
        return NewsVelocitySignal(
            status="INSUFFICIENT_BASELINE",
            as_of_ms=int(as_of_ms),
            short_window_ms=short,
            baseline_window_ms=baseline,
            current_count=0,
            current_velocity_per_min=0.0,
            baseline_bucket_count=bucket_count,
            baseline_mean_count=None,
            baseline_std_count=None,
            zscore=None,
        )

    event_list = list(events)
    current_start = int(as_of_ms) - short
    current_rows = _deduped_news(
        event_list,
        start_ms=current_start,
        end_ms=int(as_of_ms),
    )
    baseline_start = current_start - bucket_count * short
    baseline_rows = _deduped_news(
        event_list,
        start_ms=baseline_start,
        end_ms=current_start - 1,
    )
    counts = [0 for _ in range(bucket_count)]
    for row in baseline_rows:
        index = (row.event.ingest_ts_ms - baseline_start) // short
        if 0 <= index < bucket_count:
            counts[index] += 1

    mean_count = statistics.fmean(counts)
    std_count = statistics.pstdev(counts)
    current_count = len(current_rows)
    velocity = current_count / (short / 60_000.0)
    if std_count <= 0.0:
        return NewsVelocitySignal(
            status="ZERO_BASELINE_VARIANCE",
            as_of_ms=int(as_of_ms),
            short_window_ms=short,
            baseline_window_ms=baseline,
            current_count=current_count,
            current_velocity_per_min=velocity,
            baseline_bucket_count=bucket_count,
            baseline_mean_count=mean_count,
            baseline_std_count=std_count,
            zscore=None,
        )

    return NewsVelocitySignal(
        status="OK",
        as_of_ms=int(as_of_ms),
        short_window_ms=short,
        baseline_window_ms=baseline,
        current_count=current_count,
        current_velocity_per_min=velocity,
        baseline_bucket_count=bucket_count,
        baseline_mean_count=mean_count,
        baseline_std_count=std_count,
        zscore=(current_count - mean_count) / std_count,
    )


def _deduped_news(
    events: Iterable[WorldMonitorEvent],
    *,
    start_ms: int,
    end_ms: int,
) -> list[WorldMonitorEvent]:
    seen: set[tuple[str, str]] = set()
    rows: list[WorldMonitorEvent] = []
    for row in events:
        if row.kind != "news" or not row.usable_for_signal:
            continue
        ts = int(row.event.ingest_ts_ms)
        if ts < int(start_ms) or ts > int(end_ms):
            continue
        key = row.event.dedupe_key
        if key in seen:
            continue
        seen.add(key)
        rows.append(row)
    return rows


__all__ = [
    "NewsFlowFeatures",
    "NewsVelocitySignal",
    "compute_news_flow_features",
    "compute_news_velocity_zscore",
]
