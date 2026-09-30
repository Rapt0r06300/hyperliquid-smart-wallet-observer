"""Recursive feature stability checks."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class RecursiveFeatureStability:
    feature: str
    stable: bool
    max_abs_delta: float
    reason: str | None


def recursive_feature_stability(
    *,
    feature: str,
    full_series: list[float],
    incremental_series: list[float],
    tolerance: float = 1e-9,
) -> RecursiveFeatureStability:
    n = min(len(full_series), len(incremental_series))
    if n == 0:
        return RecursiveFeatureStability(feature, False, 0.0, "FEATURE_SERIES_EMPTY")
    deltas = [abs(float(full_series[i]) - float(incremental_series[i])) for i in range(n)]
    max_delta = max(deltas) if deltas else 0.0
    if max_delta > float(tolerance):
        return RecursiveFeatureStability(feature, False, round(max_delta, 12), "RECURSIVE_FEATURE_UNSTABLE")
    return RecursiveFeatureStability(feature, True, round(max_delta, 12), None)


__all__ = ["RecursiveFeatureStability", "recursive_feature_stability"]
