"""Causal runtime evidence for Event Intelligence Dataset V2.

This pipeline consumes archived structured events only. It produces source,
provenance, regime and asset-mapping evidence while remaining research-only:
it cannot authorize promotion, PnL proof or execution.
"""
from __future__ import annotations

from collections import Counter, defaultdict
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
            "reason": str(health.reason),
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
    return {
        "schema": "alina.event_intelligence_runtime_evidence.v1",
        "input_event_count": len(rows),
        "accepted_event_count": len(accepted),
        "rejection_counts": dict(sorted(rejection_counts.items())),
        "cluster_count": len(clusters),
        "provenance": provenance_rows,
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


__all__ = ["build_runtime_evidence"]
