"""Model vs market difference + bucketed distribution (S7 — V9, PolyWeather A3).

The edge a copy bot has is when its model probability diverges from the market-
implied probability. This module computes the signed difference, classifies it
into buckets, and flags when the divergence clears a threshold.

SAFETY: pure. A divergence is an observation, never an order.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True, slots=True)
class ModelMarketSignal:
    model_prob: float
    market_prob: float
    difference: float
    edge_side: str          # MODEL_HIGHER / MODEL_LOWER / ALIGNED
    actionable: bool


@dataclass(frozen=True, slots=True)
class ModelMarketDistribution:
    bucket_counts: dict[str, int] = field(default_factory=dict)
    mean_abs_difference: float | None = None
    samples: int = 0


def model_market_diff(
    model_prob: float,
    market_prob: float,
    *,
    threshold: float = 0.05,
) -> ModelMarketSignal:
    m = min(1.0, max(0.0, float(model_prob)))
    k = min(1.0, max(0.0, float(market_prob)))
    diff = m - k
    if diff >= threshold:
        side = "MODEL_HIGHER"
    elif diff <= -threshold:
        side = "MODEL_LOWER"
    else:
        side = "ALIGNED"
    return ModelMarketSignal(m, k, diff, side, actionable=abs(diff) >= threshold)


def distribution(
    pairs: list[tuple[float, float]],
    *,
    bucket_width: float = 0.05,
) -> ModelMarketDistribution:
    """Bucket signed differences (model - market) into ±width bands."""
    if not pairs:
        return ModelMarketDistribution({}, None, 0)
    counts: dict[str, int] = {}
    abs_total = 0.0
    for model_prob, market_prob in pairs:
        diff = min(1.0, max(0.0, model_prob)) - min(1.0, max(0.0, market_prob))
        abs_total += abs(diff)
        band = int(diff / bucket_width) if bucket_width > 0 else 0
        key = f"{band * bucket_width:+.2f}"
        counts[key] = counts.get(key, 0) + 1
    return ModelMarketDistribution(counts, abs_total / len(pairs), len(pairs))
