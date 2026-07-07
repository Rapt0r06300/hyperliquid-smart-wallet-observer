"""Brier score + cumulative Brier advantage (S7 — V9, pm-backtest A4).

Brier score for binary outcomes: mean((p - y)^2), lower is better.
Cumulative advantage = baseline_brier - model_brier (positive = model beats
the baseline, e.g. the market price or a naive 0.5).

SAFETY: pure statistics; no fabrication. Empty input -> ``None``.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class BrierResult:
    brier: float | None
    baseline_brier: float | None
    advantage: float | None
    samples: int


def _coerce_outcome(y: float | bool | int) -> float:
    return 1.0 if bool(y) else 0.0


def brier_score(predictions: list[tuple[float, float | bool | int]]) -> float | None:
    """``predictions`` = list of (probability, outcome)."""
    if not predictions:
        return None
    total = 0.0
    n = 0
    for prob, outcome in predictions:
        p = min(1.0, max(0.0, float(prob)))
        y = _coerce_outcome(outcome)
        total += (p - y) ** 2
        n += 1
    return total / n if n else None


def cumulative_brier_advantage(
    model_probs: list[float],
    outcomes: list[float | bool | int],
    *,
    baseline_probs: list[float] | None = None,
    baseline_constant: float = 0.5,
) -> BrierResult:
    """Compare model Brier against a baseline (market probs or a constant)."""
    n = min(len(model_probs), len(outcomes))
    if n == 0:
        return BrierResult(None, None, None, 0)
    model_preds = [(model_probs[i], outcomes[i]) for i in range(n)]
    if baseline_probs is not None and len(baseline_probs) >= n:
        base_preds = [(baseline_probs[i], outcomes[i]) for i in range(n)]
    else:
        base_preds = [(baseline_constant, outcomes[i]) for i in range(n)]

    model_b = brier_score(model_preds)
    base_b = brier_score(base_preds)
    advantage = None
    if model_b is not None and base_b is not None:
        advantage = base_b - model_b
    return BrierResult(brier=model_b, baseline_brier=base_b, advantage=advantage, samples=n)
