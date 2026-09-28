"""Fail-closed Event Intelligence bridge to Alina's canonical research families."""
from __future__ import annotations

from collections import Counter
from collections.abc import Iterable, Mapping
from dataclasses import asdict
from hl_observer.collection.native_venue_market import NativeMarketSnapshot
from hl_observer.event_intelligence.candidates import evaluate_event_lead_lag_candidate
from hl_observer.event_intelligence.module_bridges import (
    build_cross_venue_event_context,
    build_lead_lag_event_context,
)
from hl_observer.event_intelligence.outcomes import evaluate_candidate_markout
from hl_observer.event_intelligence.regimes import map_event_to_assets
from hl_observer.event_intelligence.scoreboard import ScoredEventOutcome, build_scoreboard_slices
from hl_observer.event_intelligence.worldmonitor import WorldMonitorEvent


def build_economic_research_evidence(
    events: Iterable[WorldMonitorEvent],
    snapshots: Iterable[NativeMarketSnapshot],
    *,
    cost_model: Mapping[str, float | int | None] | None = None,
    horizon_ms: int = 60_000,
    notional_usd: float = 50.0,
) -> dict[str, object]:
    """Evaluate causal event candidates without creating an execution path."""

    event_rows = tuple(events)
    snapshot_rows = tuple(snapshots)
    costs = dict(cost_model or {})
    required = ("fees_bps", "slippage_bps", "latency_bps")
    costs_complete = all(costs.get(key) is not None for key in required)
    cost_floor = (
        sum(float(costs[key]) for key in required)
        if costs_complete
        else None
    )
    candidates = []
    markouts = []
    lead_contexts = []
    cross_contexts = []
    scored: list[ScoredEventOutcome] = []
    reasons: Counter[str] = Counter()

    available_assets = sorted({row.coin for row in snapshot_rows if row.coin})
    for world_event in event_rows:
        assets = map_event_to_assets(
            world_event,
            available_assets=available_assets,
        ).assets
        if not assets:
            reasons["NO_MAPPED_ASSET"] += 1
            continue
        for asset in assets:
            post_event = [
                row.receive_ts_ms
                for row in snapshot_rows
                if row.coin == asset
                and row.receive_ts_ms >= world_event.event.available_ts_ms
            ]
            decision_ts = (
                min(post_event)
                if post_event
                else world_event.event.available_ts_ms
            )
            candidate = evaluate_event_lead_lag_candidate(
                world_event,
                snapshot_rows,
                coin=asset,
                decision_ts_ms=decision_ts,
                cost_floor_bps=cost_floor,
            )
            candidates.append(asdict(candidate))
            reasons[candidate.reason] += 1
            lead_contexts.append(asdict(build_lead_lag_event_context(
                world_event,
                candidate,
                available_assets=available_assets,
            )))
            cross_contexts.append(asdict(build_cross_venue_event_context(
                world_event,
                decision_ts_ms=decision_ts,
                available_assets=available_assets,
            )))
            outcome = evaluate_candidate_markout(
                candidate,
                snapshot_rows,
                horizon_ms=int(horizon_ms),
                fees_bps=costs.get("fees_bps"),
                slippage_bps=costs.get("slippage_bps"),
                latency_bps=costs.get("latency_bps"),
                entry_latency_ms=int(costs.get("entry_latency_ms") or 0),
                notional_usd=float(notional_usd),
            )
            markouts.append(asdict(outcome))
            if outcome.measured:
                scored.append(ScoredEventOutcome(
                    outcome=outcome,
                    event_family=world_event.kind,
                    source_tier=world_event.event.source_tier.value,
                    corroboration_count=world_event.event.corroboration_count,
                    prediction_delta_pp=world_event.probability_delta_pp,
                ))

    scoreboards = {
        key: asdict(value)
        for key, value in build_scoreboard_slices(
            scored,
            roi_denominator_usd=float(notional_usd),
        ).items()
    }
    measured = sum(1 for row in markouts if row["status"] == "MEASURED")
    return {
        "schema": "alina.event_intelligence_economic_research.v1",
        "event_count": len(event_rows),
        "snapshot_count": len(snapshot_rows),
        "cost_model_complete": costs_complete,
        "candidate_count": len(candidates),
        "measured_markout_count": measured,
        "candidates": candidates,
        "markouts": markouts,
        "lead_lag_contexts": lead_contexts,
        "cross_venue_contexts": cross_contexts,
        "copy_vault_context": {
            "status": "UNMEASURABLE",
            "reason": "LEADER_ACTIONS_NOT_PROVIDED",
        },
        "scoreboards": scoreboards,
        "reason_counts": dict(sorted(reasons.items())),
        "proof_state": "REQUIRES_SCOREBOARD" if measured else "UNMEASURABLE",
        "promotion_allowed": False,
        "paper_only": True,
        "read_only": True,
        "real_execution": False,
    }


__all__ = ["build_economic_research_evidence"]
