"""Fast / slow / blended volatility (S4 — V9 fusion).

Provides more than a single range: a *fast* sigma (reactive, short window),
a *slow* sigma (stable, long window) and a *blend* used by sizing/edge.
Volatility is expressed in basis points of per-step log return.

SAFETY: pure + deterministic. Fewer than two returns -> ``None`` and a
low ``data_quality``; never fabricated.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any

from hl_observer.features.market import safe_float


@dataclass(frozen=True, slots=True)
class VolatilityBlend:
    fast_bps: float | None
    slow_bps: float | None
    blend_bps: float | None
    bucket: str
    samples_fast: int
    samples_slow: int
    data_quality: str


def _log_returns(prices: list[float]) -> list[float]:
    out: list[float] = []
    for i in range(1, len(prices)):
        prev = prices[i - 1]
        cur = prices[i]
        if prev > 0 and cur > 0:
            out.append(math.log(cur / prev))
    return out


def _sample_stdev_bps(returns: list[float]) -> float | None:
    if len(returns) < 2:
        return None
    mean = sum(returns) / len(returns)
    var = sum((r - mean) ** 2 for r in returns) / (len(returns) - 1)
    return math.sqrt(var) * 10_000.0


def bucket_for(metric_bps: float | None) -> str:
    if metric_bps is None:
        return "UNKNOWN"
    if metric_bps < 10:
        return "LOW"
    if metric_bps < 40:
        return "NORMAL"
    if metric_bps < 120:
        return "HIGH"
    return "EXTREME"


def compute_volatility_blend(
    prices: list[Any] | None,
    *,
    fast_window: int = 12,
    slow_window: int = 60,
    fast_weight: float = 0.6,
) -> VolatilityBlend:
    """Compute fast/slow/blend sigma from a price series (oldest -> newest)."""
    if not prices:
        return VolatilityBlend(None, None, None, "UNKNOWN", 0, 0, "MISSING")
    clean = [p for p in (safe_float(x) for x in prices) if p is not None and p > 0]
    if len(clean) < 3:
        return VolatilityBlend(None, None, None, "UNKNOWN", 0, 0, "DEGRADED")

    fast_prices = clean[-(fast_window + 1):] if fast_window > 0 else clean
    slow_prices = clean[-(slow_window + 1):] if slow_window > 0 else clean
    fast_returns = _log_returns(fast_prices)
    slow_returns = _log_returns(slow_prices)
    fast_bps = _sample_stdev_bps(fast_returns)
    slow_bps = _sample_stdev_bps(slow_returns)

    weight = min(1.0, max(0.0, fast_weight))
    if fast_bps is not None and slow_bps is not None:
        blend = weight * fast_bps + (1.0 - weight) * slow_bps
        quality = "OK"
    elif fast_bps is not None:
        blend = fast_bps
        quality = "DEGRADED"
    elif slow_bps is not None:
        blend = slow_bps
        quality = "DEGRADED"
    else:
        blend = None
        quality = "DEGRADED"

    return VolatilityBlend(
        fast_bps=fast_bps,
        slow_bps=slow_bps,
        blend_bps=blend,
        bucket=bucket_for(blend),
        samples_fast=len(fast_returns),
        samples_slow=len(slow_returns),
        data_quality=quality,
    )
