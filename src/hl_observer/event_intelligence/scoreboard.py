"""Event Intelligence bridge into Alina's canonical economic scoreboard."""

from __future__ import annotations

import math
import statistics
from dataclasses import dataclass
from typing import Iterable, Sequence

from hl_observer.event_intelligence.outcomes import EventCandidateMarkout
from hl_observer.backtesting.anti_overfit_gate import sharpe
from hl_observer.event_intelligence.validation import (
    EventStudyObservation,
    IncrementalEffect,
    incremental_effect,
    independent_event_count,
)
from hl_observer.simulation.scoreboard_metrics import ScoreboardRow, assembler_ligne


@dataclass(frozen=True, slots=True)
class ScoredEventOutcome:
    outcome: EventCandidateMarkout
    event_family: str
    source_tier: str = ""
    corroboration_count: int = 1
    sample: str = "train"
    velocity_zscore: float | None = None
    surprise_score: float | None = None
    venue: str = "hyperliquid"
    prediction_delta_pp: float | None = None


@dataclass(frozen=True, slots=True)
class EventScoreboardBundle:
    scoreboard: ScoreboardRow
    incremental: IncrementalEffect
    event_count: int
    measured_count: int
    event_family: str
    asset: str
    sharpe_per_trade: float | None
    paper_only: bool = True
    real_execution: bool = False


def build_event_scoreboard(
    rows: Iterable[ScoredEventOutcome],
    *,
    strategy: str,
    event_family: str,
    asset: str,
    controls: Iterable[EventStudyObservation] = (),
    placebos: Iterable[EventStudyObservation] = (),
    roi_denominator_usd: float | None = None,
    independence_window_ms: int = 300_000,
) -> EventScoreboardBundle:
    selected = tuple(
        row
        for row in rows
        if row.event_family == str(event_family)
        and row.outcome.coin.upper() == str(asset).upper()
    )
    measured = tuple(row for row in selected if row.outcome.measured)

    event_study_rows = tuple(_to_study(row) for row in measured)
    incremental = incremental_effect(
        event_study_rows,
        tuple(controls),
        tuple(placebos),
        independence_window_ms=independence_window_ms,
    )

    n_independent = (
        independent_event_count(
            event_study_rows,
            independence_window_ms=independence_window_ms,
        )
        if event_study_rows
        else None
    )
    gross_edge_bps = _mean(
        row.outcome.gross_mid_bps
        for row in measured
        if row.outcome.gross_mid_bps is not None
    )
    fees_bps = _strict_mean(row.outcome.fees_bps for row in measured)
    spread_bps = _strict_mean(row.outcome.spread_bps for row in measured)
    slippage_bps = _strict_mean(row.outcome.slippage_bps for row in measured)
    latency_bps = _strict_mean(row.outcome.latency_bps for row in measured)

    closed_pnls = [
        float(row.outcome.net_pnl_usd)
        for row in measured
        if row.outcome.net_pnl_usd is not None
        and math.isfinite(float(row.outcome.net_pnl_usd))
    ]
    capacities = [
        float(row.outcome.capacity_usd)
        for row in measured
        if row.outcome.capacity_usd is not None
        and math.isfinite(float(row.outcome.capacity_usd))
    ]
    fill_ratios = [
        float(row.outcome.fill_ratio)
        for row in measured
        if row.outcome.fill_ratio is not None
        and math.isfinite(float(row.outcome.fill_ratio))
    ]
    latencies = sorted(
        float(row.outcome.entry_latency_ms)
        for row in measured
        if row.outcome.entry_latency_ms is not None
        and math.isfinite(float(row.outcome.entry_latency_ms))
    )

    oos_net_bps = _mean(
        row.outcome.net_bps
        for row in measured
        if row.sample == "oos" and row.outcome.net_bps is not None
    )
    forward_net_bps = _mean(
        row.outcome.net_bps
        for row in measured
        if row.sample == "forward" and row.outcome.net_bps is not None
    )
    scoreboard = assembler_ligne(
        strategy=str(strategy),
        closed_pnls=closed_pnls,
        n_independent=n_independent,
        gross_edge_bps=gross_edge_bps,
        fees_bps=fees_bps,
        spread_bps=spread_bps,
        slippage_bps=slippage_bps,
        latency_bps=latency_bps,
        roi_denominator_usd=roi_denominator_usd,
        capacity_usd=(min(capacities) if capacities else None),
        fill_ratios=fill_ratios,
        latency_p50_ms=_percentile(latencies, 0.50),
        latency_p95_ms=_percentile(latencies, 0.95),
        oos_net_bps=oos_net_bps,
        forward_net_bps=forward_net_bps,
    )
    return EventScoreboardBundle(
        scoreboard=scoreboard,
        incremental=incremental,
        event_count=len(selected),
        measured_count=len(measured),
        event_family=str(event_family),
        asset=str(asset).upper(),
        sharpe_per_trade=(round(sharpe(closed_pnls), 6) if len(closed_pnls) >= 2 else None),
    )


def build_scoreboard_slices(
    rows: Iterable[ScoredEventOutcome],
    *,
    strategy_prefix: str = "event_intelligence",
    controls: Iterable[EventStudyObservation] = (),
    placebos: Iterable[EventStudyObservation] = (),
    roi_denominator_usd: float | None = None,
) -> dict[str, EventScoreboardBundle]:
    row_list = tuple(rows)
    keys = sorted(
        {
            (row.event_family, row.outcome.coin.upper())
            for row in row_list
        }
    )
    output: dict[str, EventScoreboardBundle] = {}
    for family, asset in keys:
        key = f"{family}:{asset}"
        output[key] = build_event_scoreboard(
            row_list,
            strategy=f"{strategy_prefix}:{family}:{asset}",
            event_family=family,
            asset=asset,
            controls=tuple(
                row
                for row in controls
                if row.event_family == family and row.asset.upper() == asset
            ),
            placebos=tuple(
                row
                for row in placebos
                if row.event_family == family and row.asset.upper() == asset
            ),
            roi_denominator_usd=roi_denominator_usd,
        )
    return output


def _to_study(row: ScoredEventOutcome) -> EventStudyObservation:
    outcome = row.outcome
    return EventStudyObservation(
        observation_id=f"{outcome.event_id}:{outcome.decision_ts_ms}:{outcome.horizon_ms}",
        ts_ms=int(outcome.decision_ts_ms),
        event_family=str(row.event_family),
        asset=outcome.coin.upper(),
        net_bps=outcome.net_bps,
        net_pnl_usd=outcome.net_pnl_usd,
        end_ts_ms=outcome.exit_ts_ms,
        sample=str(row.sample),
        source_tier=str(row.source_tier),
        venue=str(row.venue),
        session="",
        corroboration_count=int(row.corroboration_count),
        velocity_zscore=row.velocity_zscore,
        surprise_score=row.surprise_score,
        prediction_delta_pp=row.prediction_delta_pp,
    )


def _strict_mean(values: Iterable[float | None]) -> float | None:
    raw = list(values)
    if not raw or any(value is None for value in raw):
        return None
    parsed = [float(value) for value in raw if value is not None]
    if len(parsed) != len(raw) or any(not math.isfinite(value) for value in parsed):
        return None
    return round(statistics.fmean(parsed), 8)


def _mean(values: Iterable[float | None]) -> float | None:
    parsed = [
        float(value)
        for value in values
        if value is not None and math.isfinite(float(value))
    ]
    return round(statistics.fmean(parsed), 8) if parsed else None


def _percentile(values: Sequence[float], q: float) -> float | None:
    if not values:
        return None
    ordered = sorted(float(value) for value in values)
    if len(ordered) == 1:
        return round(ordered[0], 6)
    position = (len(ordered) - 1) * float(q)
    lo = int(math.floor(position))
    hi = int(math.ceil(position))
    if lo == hi:
        return round(ordered[lo], 6)
    weight = position - lo
    return round(ordered[lo] * (1.0 - weight) + ordered[hi] * weight, 6)


__all__ = [
    "EventScoreboardBundle",
    "ScoredEventOutcome",
    "build_event_scoreboard",
    "build_scoreboard_slices",
]
