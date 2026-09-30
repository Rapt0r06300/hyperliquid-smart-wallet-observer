"""Rolling funding-rate stats."""

from __future__ import annotations

from dataclasses import dataclass
from statistics import mean, pstdev


@dataclass(frozen=True, slots=True)
class FundingWindowStats:
    count: int
    mean_rate: float
    std_rate: float
    latest_rate: float | None
    z_score: float | None


def funding_window_stats(rates: list[float]) -> FundingWindowStats:
    vals = [float(x) for x in rates]
    if not vals:
        return FundingWindowStats(0, 0.0, 0.0, None, None)
    mu = mean(vals)
    sd = pstdev(vals) if len(vals) > 1 else 0.0
    latest = vals[-1]
    z = None if sd <= 0 else (latest - mu) / sd
    return FundingWindowStats(len(vals), round(mu, 10), round(sd, 10), round(latest, 10), round(z, 8) if z is not None else None)


__all__ = ["FundingWindowStats", "funding_window_stats"]
