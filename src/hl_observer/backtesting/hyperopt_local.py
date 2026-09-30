"""Tiny local-only hyperopt/ranking harness for paper strategy configs."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, Iterable


@dataclass(frozen=True, slots=True)
class HyperoptCandidate:
    params: dict[str, object]
    score: float
    metrics: dict[str, float] = field(default_factory=dict)


def hyperopt_local_only(
    candidates: Iterable[dict[str, object]],
    objective_fn: Callable[[dict[str, object]], tuple[float, dict[str, float]]],
    *,
    limit: int = 20,
) -> list[HyperoptCandidate]:
    rows: list[HyperoptCandidate] = []
    for params in candidates:
        score, metrics = objective_fn(dict(params))
        rows.append(HyperoptCandidate(params=dict(params), score=float(score), metrics=dict(metrics)))
    rows.sort(key=lambda item: item.score, reverse=True)
    return rows[: max(0, int(limit))]


__all__ = ["HyperoptCandidate", "hyperopt_local_only"]
