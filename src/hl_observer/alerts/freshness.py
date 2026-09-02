"""Deterministic freshness and latency projection for canonical alerts."""

from __future__ import annotations

import math
from collections import defaultdict
from collections.abc import Mapping, Sequence
from typing import Any

FRESHNESS_POLICY_VERSION = "hypersmart.alert_freshness.v1"
FRESH_MAX_AGE_MS = 30_000
DEGRADED_MAX_AGE_MS = 120_000
DETECTION_TO_DISPLAY_SLO_MS = 15_000


def _percentile(values: Sequence[int], quantile: float) -> int | None:
    if not values:
        return None
    ordered = sorted(int(value) for value in values)
    index = max(0, math.ceil(quantile * len(ordered)) - 1)
    return ordered[index]


def _distribution(values: Sequence[int]) -> dict[str, int | None]:
    return {
        "count": len(values),
        "p50_ms": _percentile(values, 0.50),
        "p95_ms": _percentile(values, 0.95),
        "p99_ms": _percentile(values, 0.99),
    }


def _effective_freshness(age_ms: int) -> str:
    if age_ms <= FRESH_MAX_AGE_MS:
        return "FRESH"
    if age_ms <= DEGRADED_MAX_AGE_MS:
        return "DEGRADED"
    return "STALE"


def project_alert_freshness(
    events: Sequence[Mapping[str, Any]],
    *,
    projected_at_ms: int,
    displayed_at_ms: int | None,
) -> dict[str, Any]:
    """Project per-event clocks and aggregate source/category health."""

    event_states: dict[str, dict[str, Any]] = {}
    grouped: dict[tuple[str, str], dict[str, list[int]]] = defaultdict(
        lambda: defaultdict(list)
    )
    latest_by_source: dict[str, Mapping[str, Any]] = {}
    source_gap_counts: dict[str, list[int]] = defaultdict(list)

    for event in events:
        event_id = str(event["event_id"])
        observed = int(event["observed_at_ms"])
        fetched = int(event["fetched_at_ms"])
        parsed = int(event["parsed_at_ms"])
        verified = int(event["verified_at_ms"])
        admitted = int(event["admitted_at_ms"])
        source_event = event.get("source_event_time_ms")
        source_available = int(event["source_available_time_ms"])
        age_ms = max(0, projected_at_ms - observed)
        effective_freshness = _effective_freshness(age_ms)
        declared_health = str(event["source_health_state"])
        if effective_freshness == "STALE":
            effective_health = "STALE"
        elif effective_freshness == "DEGRADED" and declared_health == "HEALTHY":
            effective_health = "DEGRADED"
        else:
            effective_health = declared_health
        lags: dict[str, int | None] = {
            "source_to_observation_ms": (
                observed - int(source_event) if source_event is not None else None
            ),
            "availability_to_observation_ms": observed - source_available,
            "observation_to_fetch_ms": fetched - observed,
            "fetch_to_parse_ms": parsed - fetched,
            "parse_to_verify_ms": verified - parsed,
            "verify_to_admit_ms": admitted - verified,
            "admit_to_projection_ms": projected_at_ms - admitted,
            "detection_to_display_ms": (
                displayed_at_ms - observed if displayed_at_ms is not None else None
            ),
        }
        detection_to_display = lags["detection_to_display_ms"]
        display_slo_state = (
            "NOT_DISPLAYED"
            if detection_to_display is None
            else (
                "MEETS_SLO"
                if detection_to_display <= DETECTION_TO_DISPLAY_SLO_MS
                else "BREACH"
            )
        )
        event_states[event_id] = {
            "source_timestamp_ms": (
                int(source_event) if source_event is not None else None
            ),
            "observed_at_ms": observed,
            "last_successful_refresh_ms": fetched,
            "effective_freshness_state": effective_freshness,
            "effective_source_health_state": effective_health,
            "age_ms": age_ms,
            "stale_source_duration_ms": (
                max(0, age_ms - DEGRADED_MAX_AGE_MS)
                if effective_freshness == "STALE"
                else 0
            ),
            "latency": lags,
            "display_slo_state": display_slo_state,
            "no_news_conclusion_valid": (
                str(event.get("category")) != "NO_NEWS"
                or (
                    effective_health == "HEALTHY"
                    and effective_freshness == "FRESH"
                )
            ),
        }
        for group in (
            ("source", str(event["source_id"])),
            ("category", str(event["category"])),
        ):
            for metric, value in lags.items():
                if value is not None:
                    grouped[group][metric].append(int(value))
        source_id = str(event["source_id"])
        previous = latest_by_source.get(source_id)
        if previous is None or int(previous["observed_at_ms"]) <= observed:
            latest_by_source[source_id] = event
        source_gap_counts[source_id].append(int(event.get("producer_gap_size", 0)))

    aggregate: dict[str, dict[str, dict[str, dict[str, int | None]]]] = {
        "source": {},
        "category": {},
    }
    for (group_kind, group_value), metrics in sorted(grouped.items()):
        aggregate[group_kind][group_value] = {
            metric: _distribution(values)
            for metric, values in sorted(metrics.items())
        }

    source_health: dict[str, dict[str, Any]] = {}
    for source_id, event in sorted(latest_by_source.items()):
        state = event_states[str(event["event_id"])]
        gaps = source_gap_counts[source_id]
        missing = sum(gaps)
        observed_slots = len(gaps) + missing
        source_health[source_id] = {
            "declared_health_state": event["source_health_state"],
            "effective_health_state": state["effective_source_health_state"],
            "effective_freshness_state": state["effective_freshness_state"],
            "last_observed_at_ms": int(event["observed_at_ms"]),
            "last_successful_refresh_ms": int(event["fetched_at_ms"]),
            "age_ms": state["age_ms"],
            "stale_source_duration_ms": state["stale_source_duration_ms"],
            "missed_poll_or_gap_rate": (
                round(missing / observed_slots, 6) if observed_slots else 0.0
            ),
            "gap_count": missing,
        }

    return {
        "schema_version": FRESHNESS_POLICY_VERSION,
        "policy": {
            "fresh_max_age_ms": FRESH_MAX_AGE_MS,
            "degraded_max_age_ms": DEGRADED_MAX_AGE_MS,
            "detection_to_display_slo_ms": DETECTION_TO_DISPLAY_SLO_MS,
        },
        "event_states": event_states,
        "source_health": source_health,
        "latency_distributions": aggregate,
    }


__all__ = [
    "DEGRADED_MAX_AGE_MS",
    "DETECTION_TO_DISPLAY_SLO_MS",
    "FRESHNESS_POLICY_VERSION",
    "FRESH_MAX_AGE_MS",
    "project_alert_freshness",
]
