"""Measure latency between leader event, observation and paper decision."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class CopyLatencyProfile:
    leader_to_observed_ms: int | None
    observed_to_decision_ms: int | None
    total_ms: int | None
    warning: str | None


def profile_copy_latency(
    *,
    leader_time_ms: int | None,
    observed_time_ms: int,
    decision_time_ms: int,
    warn_ms: int = 1_000,
) -> CopyLatencyProfile:
    leader_to_observed = None if leader_time_ms is None else max(0, int(observed_time_ms) - int(leader_time_ms))
    observed_to_decision = max(0, int(decision_time_ms) - int(observed_time_ms))
    total = None if leader_time_ms is None else max(0, int(decision_time_ms) - int(leader_time_ms))
    warning = None
    if total is None:
        warning = "LEADER_TIME_MISSING"
    elif total > int(warn_ms):
        warning = "COPY_LATENCY_WARN"
    return CopyLatencyProfile(
        leader_to_observed_ms=leader_to_observed,
        observed_to_decision_ms=observed_to_decision,
        total_ms=total,
        warning=warning,
    )


__all__ = ["CopyLatencyProfile", "profile_copy_latency"]
