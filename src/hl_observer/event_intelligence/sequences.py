"""Causal propagation-sequence library for Event Intelligence."""

from __future__ import annotations

import math
import statistics
from dataclasses import dataclass
from enum import StrEnum
from typing import Iterable


class PropagationStage(StrEnum):
    PREDICTION = "PREDICTION"
    NEWS = "NEWS"
    EXTERNAL_EVENT = "EXTERNAL_EVENT"
    MARKET_LEADER = "MARKET_LEADER"
    HYPERLIQUID = "HYPERLIQUID"
    LIQUIDATION = "LIQUIDATION"


@dataclass(frozen=True, slots=True)
class StageObservation:
    stage: PropagationStage
    ts_ms: int
    source: str = ""
    asset: str = ""
    event_id: str = ""


@dataclass(frozen=True, slots=True)
class PropagationPattern:
    stages: tuple[PropagationStage, ...]
    timestamps_ms: tuple[int, ...]
    total_latency_ms: int
    inter_stage_ms: tuple[int, ...]
    causal: bool
    pattern_id: str


@dataclass(frozen=True, slots=True)
class PatternStats:
    pattern_id: str
    observations: int
    median_total_latency_ms: float | None
    p90_total_latency_ms: float | None
    median_inter_stage_ms: tuple[float, ...]


def build_propagation_pattern(
    observations: Iterable[StageObservation],
) -> PropagationPattern | None:
    rows = sorted(
        observations,
        key=lambda row: (int(row.ts_ms), row.stage.value, row.source),
    )
    if len(rows) < 2:
        return None
    timestamps = tuple(int(row.ts_ms) for row in rows)
    stages = tuple(row.stage for row in rows)
    causal = all(
        later >= earlier for earlier, later in zip(timestamps, timestamps[1:])
    )
    gaps = tuple(
        later - earlier for earlier, later in zip(timestamps, timestamps[1:])
    )
    pattern_id = ">".join(stage.value for stage in stages)
    return PropagationPattern(
        stages=stages,
        timestamps_ms=timestamps,
        total_latency_ms=timestamps[-1] - timestamps[0],
        inter_stage_ms=gaps,
        causal=causal,
        pattern_id=pattern_id,
    )


def summarize_patterns(
    patterns: Iterable[PropagationPattern],
    *,
    causal_only: bool = True,
) -> dict[str, PatternStats]:
    groups: dict[str, list[PropagationPattern]] = {}
    for pattern in patterns:
        if causal_only and not pattern.causal:
            continue
        groups.setdefault(pattern.pattern_id, []).append(pattern)

    output: dict[str, PatternStats] = {}
    for pattern_id, rows in sorted(groups.items()):
        totals = [float(row.total_latency_ms) for row in rows]
        max_steps = max((len(row.inter_stage_ms) for row in rows), default=0)
        medians: list[float] = []
        for index in range(max_steps):
            values = [
                float(row.inter_stage_ms[index])
                for row in rows
                if index < len(row.inter_stage_ms)
            ]
            medians.append(
                round(statistics.median(values), 6) if values else math.nan
            )
        output[pattern_id] = PatternStats(
            pattern_id=pattern_id,
            observations=len(rows),
            median_total_latency_ms=(
                round(statistics.median(totals), 6) if totals else None
            ),
            p90_total_latency_ms=_percentile(totals, 0.90),
            median_inter_stage_ms=tuple(medians),
        )
    return output


def _percentile(values: list[float], q: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    if len(ordered) == 1:
        return round(ordered[0], 6)
    pos = (len(ordered) - 1) * float(q)
    lo = int(math.floor(pos))
    hi = int(math.ceil(pos))
    if lo == hi:
        return round(ordered[lo], 6)
    weight = pos - lo
    return round(ordered[lo] * (1.0 - weight) + ordered[hi] * weight, 6)


__all__ = [
    "PatternStats",
    "PropagationPattern",
    "PropagationStage",
    "StageObservation",
    "build_propagation_pattern",
    "summarize_patterns",
]
