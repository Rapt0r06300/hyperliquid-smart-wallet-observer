"""Confidence-bucket calibration (S7 — V9, CloddsBot A1).

Group predictions into confidence buckets and measure the *realised* win-rate
per bucket. A well-calibrated model has realised win-rate ≈ mean confidence in
each bucket; the calibration error summarises the gap.

SAFETY: pure. Empty buckets report 0 count, never invented win-rates.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class ConfidenceBucket:
    low: float
    high: float
    count: int
    win_rate: float | None
    mean_confidence: float | None

    @property
    def calibration_gap(self) -> float | None:
        if self.win_rate is None or self.mean_confidence is None:
            return None
        return abs(self.win_rate - self.mean_confidence)


def bucketize(
    samples: list[tuple[float, float | bool | int]],
    *,
    n_buckets: int = 10,
) -> list[ConfidenceBucket]:
    """``samples`` = list of (confidence in [0,1], win outcome)."""
    n_buckets = max(1, n_buckets)
    edges = [i / n_buckets for i in range(n_buckets + 1)]
    confs: list[list[float]] = [[] for _ in range(n_buckets)]
    wins: list[list[float]] = [[] for _ in range(n_buckets)]

    for conf, outcome in samples:
        c = min(1.0, max(0.0, float(conf)))
        idx = min(n_buckets - 1, int(c * n_buckets))
        confs[idx].append(c)
        wins[idx].append(1.0 if bool(outcome) else 0.0)

    buckets: list[ConfidenceBucket] = []
    for i in range(n_buckets):
        count = len(wins[i])
        win_rate = (sum(wins[i]) / count) if count else None
        mean_conf = (sum(confs[i]) / count) if count else None
        buckets.append(ConfidenceBucket(edges[i], edges[i + 1], count, win_rate, mean_conf))
    return buckets


def calibration_error(buckets: list[ConfidenceBucket]) -> float | None:
    """Sample-weighted mean absolute gap between win-rate and confidence."""
    total = 0.0
    weight = 0
    for b in buckets:
        gap = b.calibration_gap
        if gap is not None and b.count > 0:
            total += gap * b.count
            weight += b.count
    if weight == 0:
        return None
    return total / weight
