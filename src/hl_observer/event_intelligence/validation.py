"""Causal validation primitives for Event Intelligence research.

The goal is to prove incremental value versus matched NO_EVENT and placebo samples,
not merely to show that some events happened before profitable markouts.
"""

from __future__ import annotations

import math
import statistics
from dataclasses import dataclass
from typing import Iterable, Sequence


@dataclass(frozen=True, slots=True)
class EventStudyObservation:
    observation_id: str
    ts_ms: int
    event_family: str
    asset: str
    net_bps: float | None
    net_pnl_usd: float | None
    sample: str = "train"
    source_tier: str = ""
    corroboration_count: int = 1
    velocity_zscore: float | None = None
    surprise_score: float | None = None


@dataclass(frozen=True, slots=True)
class ChronologicalSplit:
    train: tuple[EventStudyObservation, ...]
    oos: tuple[EventStudyObservation, ...]
    forward: tuple[EventStudyObservation, ...]
    embargo_ms: int


@dataclass(frozen=True, slots=True)
class IncrementalEffect:
    event_count: int
    control_count: int
    placebo_count: int
    event_mean_net_bps: float | None
    control_mean_net_bps: float | None
    placebo_mean_net_bps: float | None
    incremental_vs_control_bps: float | None
    incremental_vs_placebo_bps: float | None
    event_mean_pnl_usd: float | None
    control_mean_pnl_usd: float | None
    placebo_mean_pnl_usd: float | None
    verdict: str


def chronological_split(
    rows: Sequence[EventStudyObservation],
    *,
    train_fraction: float = 0.60,
    oos_fraction: float = 0.20,
    embargo_ms: int = 0,
) -> ChronologicalSplit:
    """Chronological train/OOS/forward split with optional embargo after boundaries."""

    train_fraction = float(train_fraction)
    oos_fraction = float(oos_fraction)
    if not 0.0 < train_fraction < 1.0:
        raise ValueError("train_fraction must be in (0,1)")
    if not 0.0 < oos_fraction < 1.0:
        raise ValueError("oos_fraction must be in (0,1)")
    if train_fraction + oos_fraction >= 1.0:
        raise ValueError("forward fraction must be positive")
    embargo = max(0, int(embargo_ms))
    ordered = sorted(rows, key=lambda row: (int(row.ts_ms), row.observation_id))
    if not ordered:
        return ChronologicalSplit((), (), (), embargo)

    n = len(ordered)
    train_end_index = max(1, min(n - 2, int(n * train_fraction))) if n >= 3 else 1
    oos_end_index = (
        max(train_end_index + 1, min(n - 1, int(n * (train_fraction + oos_fraction))))
        if n >= 3
        else min(n, train_end_index + 1)
    )
    train_raw = ordered[:train_end_index]
    oos_raw = ordered[train_end_index:oos_end_index]
    forward_raw = ordered[oos_end_index:]

    train_cut = train_raw[-1].ts_ms if train_raw else -1
    oos_cut = oos_raw[-1].ts_ms if oos_raw else train_cut

    train = tuple(train_raw)
    oos = tuple(
        row for row in oos_raw if row.ts_ms > train_cut + embargo
    )
    forward = tuple(
        row for row in forward_raw if row.ts_ms > oos_cut + embargo
    )
    return ChronologicalSplit(train, oos, forward, embargo)


def independent_event_count(
    rows: Iterable[EventStudyObservation],
    *,
    independence_window_ms: int = 300_000,
) -> int:
    """Collapse nearby same-family/same-asset observations into one independent episode."""

    window = max(0, int(independence_window_ms))
    grouped: dict[tuple[str, str], list[int]] = {}
    for row in rows:
        key = (str(row.event_family), str(row.asset).upper())
        grouped.setdefault(key, []).append(int(row.ts_ms))

    count = 0
    for timestamps in grouped.values():
        last: int | None = None
        for ts in sorted(timestamps):
            if last is None or ts - last > window:
                count += 1
                last = ts
    return count


def select_no_event_controls(
    *,
    event_timestamps_ms: Sequence[int],
    candidate_timestamps_ms: Sequence[int],
    exclusion_window_ms: int = 300_000,
    max_controls: int | None = None,
) -> tuple[int, ...]:
    """Select deterministic timestamps outside every event exclusion window."""

    exclusion = max(0, int(exclusion_window_ms))
    events = sorted(int(ts) for ts in event_timestamps_ms)
    controls: list[int] = []
    for candidate in sorted({int(ts) for ts in candidate_timestamps_ms}):
        if any(abs(candidate - event_ts) <= exclusion for event_ts in events):
            continue
        controls.append(candidate)
        if max_controls is not None and len(controls) >= int(max_controls):
            break
    return tuple(controls)


def placebo_timestamps(
    event_timestamps_ms: Sequence[int],
    *,
    shifts_ms: Sequence[int] = (-3_600_000, -1_800_000, 1_800_000, 3_600_000),
    minimum_separation_ms: int = 300_000,
) -> tuple[int, ...]:
    """Generate deterministic shifted timestamps while avoiding true event windows."""

    real = sorted({int(ts) for ts in event_timestamps_ms})
    separation = max(0, int(minimum_separation_ms))
    output: set[int] = set()
    for ts in real:
        for shift in shifts_ms:
            shifted = ts + int(shift)
            if shifted < 0:
                continue
            if any(abs(shifted - actual) <= separation for actual in real):
                continue
            output.add(shifted)
    return tuple(sorted(output))


def incremental_effect(
    event_rows: Iterable[EventStudyObservation],
    control_rows: Iterable[EventStudyObservation],
    placebo_rows: Iterable[EventStudyObservation],
    *,
    min_independent_events: int = 20,
    independence_window_ms: int = 300_000,
) -> IncrementalEffect:
    events = tuple(event_rows)
    controls = tuple(control_rows)
    placebos = tuple(placebo_rows)

    event_net = _finite_values(row.net_bps for row in events)
    control_net = _finite_values(row.net_bps for row in controls)
    placebo_net = _finite_values(row.net_bps for row in placebos)
    event_pnl = _finite_values(row.net_pnl_usd for row in events)
    control_pnl = _finite_values(row.net_pnl_usd for row in controls)
    placebo_pnl = _finite_values(row.net_pnl_usd for row in placebos)

    event_mean = _mean(event_net)
    control_mean = _mean(control_net)
    placebo_mean = _mean(placebo_net)
    vs_control = (
        event_mean - control_mean
        if event_mean is not None and control_mean is not None
        else None
    )
    vs_placebo = (
        event_mean - placebo_mean
        if event_mean is not None and placebo_mean is not None
        else None
    )
    n_indep = independent_event_count(
        events,
        independence_window_ms=independence_window_ms,
    )

    if (
        event_mean is None
        or control_mean is None
        or placebo_mean is None
        or vs_control is None
        or vs_placebo is None
    ):
        verdict = "UNMEASURABLE"
    elif event_mean < 0 or vs_control < 0 or vs_placebo < 0:
        verdict = "KILL"
    elif n_indep < int(min_independent_events):
        verdict = "MORE_DATA"
    elif event_mean > 0 and vs_control > 0 and vs_placebo > 0:
        verdict = "INCREMENTAL_EDGE_CANDIDATE"
    else:
        verdict = "MORE_DATA"

    return IncrementalEffect(
        event_count=len(events),
        control_count=len(controls),
        placebo_count=len(placebos),
        event_mean_net_bps=event_mean,
        control_mean_net_bps=control_mean,
        placebo_mean_net_bps=placebo_mean,
        incremental_vs_control_bps=vs_control,
        incremental_vs_placebo_bps=vs_placebo,
        event_mean_pnl_usd=_mean(event_pnl),
        control_mean_pnl_usd=_mean(control_pnl),
        placebo_mean_pnl_usd=_mean(placebo_pnl),
        verdict=verdict,
    )


def stratify(
    rows: Iterable[EventStudyObservation],
    *,
    field: str,
) -> dict[str, tuple[EventStudyObservation, ...]]:
    """Group observations by an approved research dimension."""

    allowed = {
        "event_family",
        "asset",
        "sample",
        "source_tier",
        "corroboration_count",
    }
    if field not in allowed:
        raise ValueError("unsupported stratification field")
    groups: dict[str, list[EventStudyObservation]] = {}
    for row in rows:
        value = getattr(row, field)
        key = str(value)
        groups.setdefault(key, []).append(row)
    return {
        key: tuple(sorted(values, key=lambda row: (row.ts_ms, row.observation_id)))
        for key, values in sorted(groups.items())
    }


def _finite_values(values: Iterable[float | None]) -> list[float]:
    output: list[float] = []
    for value in values:
        if value is None:
            continue
        parsed = float(value)
        if math.isfinite(parsed):
            output.append(parsed)
    return output


def _mean(values: Sequence[float]) -> float | None:
    return round(statistics.fmean(values), 8) if values else None


__all__ = [
    "ChronologicalSplit",
    "EventStudyObservation",
    "IncrementalEffect",
    "chronological_split",
    "independent_event_count",
    "incremental_effect",
    "placebo_timestamps",
    "select_no_event_controls",
    "stratify",
]
