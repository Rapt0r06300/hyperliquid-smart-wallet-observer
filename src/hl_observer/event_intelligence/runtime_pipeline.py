"""Causal runtime evidence for Event Intelligence Dataset V2.

This pipeline consumes archived structured events only. It produces source,
provenance, regime and asset-mapping evidence while remaining research-only:
it cannot authorize promotion, PnL proof or execution.
"""
from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import asdict
from collections.abc import Iterable

from hl_observer.event_intelligence.external_event import (
    ExternalEvent,
    ExternalEventReplayGuard,
)
from hl_observer.event_intelligence.health import (
    detect_intelligence_gap,
    evaluate_direct_source_health,
)
from hl_observer.event_intelligence.provenance import (
    cluster_external_events,
    score_provenance,
)
from hl_observer.event_intelligence.regimes import (
    classify_event_regime,
    map_event_to_assets,
)
from hl_observer.event_intelligence.source_catalog import build_source_catalog
from hl_observer.event_intelligence.sequences import (
    PropagationStage,
    StageObservation,
    build_propagation_pattern,
    summarize_patterns,
)
from hl_observer.event_intelligence.protocol import assert_forward_after_freeze, freeze_event_research
from hl_observer.event_intelligence.validation import (
    EventStudyObservation,
    compare_source_latency,
    incremental_effect,
    placebo_timestamps,
    purged_chronological_split,
    select_no_event_controls,
)


def build_runtime_evidence(
    events: Iterable[ExternalEvent],
    *,
    now_ms: int,
    expected_sources: Iterable[str] = (),
    max_source_age_ms: int = 300_000,
) -> dict[str, object]:
    rows = tuple(sorted(events, key=lambda row: (row.ingest_ts_ms, row.source, row.event_id, row.revision)))
    guard = ExternalEventReplayGuard()
    accepted: list[ExternalEvent] = []
    rejection_counts: Counter[str] = Counter()
    for event in rows:
        decision = guard.observe(event, decision_ts_ms=int(now_ms))
        if decision.accepted:
            accepted.append(event)
        else:
            rejection_counts[decision.reason] += 1

    clusters = cluster_external_events(accepted)
    event_by_id = {event.event_id: event for event in accepted}
    provenance_rows: list[dict[str, object]] = []
    source_latency_rows: list[dict[str, object]] = []
    propagation_patterns = []
    for cluster in clusters:
        cluster_events = [event_by_id[event_id] for event_id in cluster.event_ids if event_id in event_by_id]
        if not cluster_events:
            continue
        score = score_provenance(cluster_events)
        provenance_rows.append({
            "cluster_id": cluster.cluster_id,
            "event_ids": list(cluster.event_ids),
            "sources": list(cluster.sources),
            "score": score.score,
            "independent_sources": score.independent_sources,
            "source_tiers": list(score.source_tiers),
            "triangulated": score.triangulated,
            "corroboration_latency_ms": score.corroboration_latency_ms,
        })
        ordered_cluster = sorted(cluster_events, key=lambda row: (row.ingest_ts_ms, row.source))
        observations = []
        for event in ordered_cluster:
            stage = (
                PropagationStage.PREDICTION
                if event.event_type.value == "PREDICTION"
                else PropagationStage.NEWS
                if event.event_type.value == "NEWS"
                else PropagationStage.EXTERNAL_EVENT
            )
            observations.append(StageObservation(
                stage=stage,
                ts_ms=event.ingest_ts_ms,
                source=event.source,
                event_id=event.event_id,
            ))
        pattern = build_propagation_pattern(observations)
        if pattern is not None:
            propagation_patterns.append(pattern)
        if (
            len(ordered_cluster) >= 2
            and ordered_cluster[0].source_tier.value == "PRIMARY_OFFICIAL"
            and ordered_cluster[-1].source_tier.value != "PRIMARY_OFFICIAL"
        ):
            latency = compare_source_latency(ordered_cluster[0], ordered_cluster[-1])
            source_latency_rows.append({
                "cluster_id": cluster.cluster_id,
                "primary_source": latency.primary_source,
                "aggregator_source": latency.aggregator_source,
                "primary_ingest_ts_ms": latency.primary_ingest_ts_ms,
                "aggregator_ingest_ts_ms": latency.aggregator_ingest_ts_ms,
                "aggregator_lag_ms": latency.aggregator_lag_ms,
            })

    regimes: Counter[str] = Counter()
    mapped_assets: Counter[str] = Counter()
    for event in accepted:
        label = classify_event_regime(
            event,
            market_moved=False,
            liquidation_spike=False,
            event_available_before_move=event.ingest_ts_ms <= int(now_ms),
        )
        regimes[label.regime.value] += 1
        relevance = map_event_to_assets(event)
        mapped_assets.update(relevance.assets)

    by_source: dict[str, list[ExternalEvent]] = defaultdict(list)
    for event in accepted:
        by_source[event.source].append(event)
    source_ids = sorted(set(str(value) for value in expected_sources if str(value)) | set(by_source))
    source_health: dict[str, dict[str, object]] = {}
    for source in source_ids:
        source_events = by_source.get(source, [])
        last_success = max((event.ingest_ts_ms for event in source_events), default=None)
        gap = detect_intelligence_gap(
            source=source,
            last_success_ms=last_success,
            now_ms=int(now_ms),
            max_age_ms=int(max_source_age_ms),
            fetch_ok=bool(source_events),
        )
        health = evaluate_direct_source_health(
            source_events,
            last_fetch_ms=last_success,
            now_ms=int(now_ms),
            max_age_ms=int(max_source_age_ms),
            fetch_ok=bool(source_events),
            contract_complete=True,
        )
        source_health[source] = {
            "status": str(health.status),
            "reasons": list(health.reasons),
            "technically_healthy": health.techniquement_sain,
            "fresh_signals": health.produit_des_signaux_frais,
            "usable": health.utilisable,
            "last_success_ms": last_success,
            "gap": (
                {
                    "reason": gap.reason,
                    "gap_age_ms": gap.gap_age_ms,
                    "detected_at_ms": gap.detected_at_ms,
                }
                if gap is not None
                else None
            ),
        }

    catalog = build_source_catalog()
    pattern_stats = summarize_patterns(propagation_patterns)
    return {
        "schema": "alina.event_intelligence_runtime_evidence.v1",
        "input_event_count": len(rows),
        "accepted_event_count": len(accepted),
        "rejection_counts": dict(sorted(rejection_counts.items())),
        "cluster_count": len(clusters),
        "provenance": provenance_rows,
        "source_latency": source_latency_rows,
        "propagation_patterns": {
            key: {
                "observations": value.observations,
                "median_total_latency_ms": value.median_total_latency_ms,
                "p90_total_latency_ms": value.p90_total_latency_ms,
                "median_inter_stage_ms": list(value.median_inter_stage_ms),
            }
            for key, value in sorted(pattern_stats.items())
        },
        "regime_counts": dict(sorted(regimes.items())),
        "mapped_asset_counts": dict(sorted(mapped_assets.items())),
        "source_health": source_health,
        "source_catalog_version": catalog.version,
        "source_catalog_ids": list(catalog.source_ids),
        "proof_state": "STRUCTURAL_ONLY",
        "proof_of_pnl_allowed": False,
        "paper_only": True,
        "read_only": True,
        "real_execution": False,
    }


def build_research_protocol_evidence(
    observations: Iterable[EventStudyObservation],
    *,
    now_ms: int,
    methodology_version: str,
    config: dict[str, object] | None = None,
    embargo_ms: int = 300_000,
    minimum_independent_events: int = 20,
) -> dict[str, object]:
    rows = tuple(sorted(observations, key=lambda row: (row.ts_ms, row.observation_id)))
    split = purged_chronological_split(rows, embargo_ms=int(embargo_ms))
    training_cutoff_ms = max(
        (row.end_ts_ms if row.end_ts_ms is not None else row.ts_ms for row in split.train),
        default=int(now_ms),
    )
    freeze = freeze_event_research(
        config or {},
        training_cutoff_ms=int(training_cutoff_ms),
        created_at_ms=int(now_ms),
        methodology_version=str(methodology_version),
    )
    for row in split.forward:
        assert_forward_after_freeze(freeze, observation_ts_ms=row.ts_ms)
    event_timestamps = tuple(row.ts_ms for row in rows)
    controls = select_no_event_controls(
        event_timestamps_ms=event_timestamps,
        candidate_timestamps_ms=(),
    )
    placebos = placebo_timestamps(event_timestamps)
    effect = incremental_effect(
        split.oos,
        (),
        (),
        min_independent_events=int(minimum_independent_events),
    )
    return {
        "schema": "alina.event_intelligence_research_protocol.v1",
        "observation_count": len(rows),
        "train_count": len(split.train),
        "oos_count": len(split.oos),
        "forward_count": len(split.forward),
        "embargo_ms": split.embargo_ms,
        "control_timestamps_ms": list(controls),
        "placebo_timestamps_ms": list(placebos),
        "freeze": asdict(freeze),
        "incremental_effect": asdict(effect),
        "proof_state": "UNMEASURABLE" if not rows else "REQUIRES_SCOREBOARD",
        "proof_of_pnl_allowed": False,
        "paper_only": True,
        "read_only": True,
        "real_execution": False,
    }


__all__ = ["build_research_protocol_evidence", "build_runtime_evidence"]
