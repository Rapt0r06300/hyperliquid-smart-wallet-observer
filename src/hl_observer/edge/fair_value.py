"""Fair-value model + edge in bps + spike/dip detection (S6 — V9, mlmodelpoly A2).

Two modes:
  * ``fast``   — reactive EMA (small alpha smoothing horizon), catches spikes.
  * ``smooth`` — stable EMA, less noise, used as the reference fair value.

Edge is the signed gap between fair value and the observed mid, in bps.
Spike/dip is flagged when the latest move exceeds ``k`` * realized sigma.

SAFETY: pure. Insufficient data -> ``None`` + low ``data_quality``.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any, Literal

from hl_observer.features.market import safe_float

Mode = Literal["fast", "smooth"]


@dataclass(frozen=True, slots=True)
class FairValue:
    fair_value: float | None
    mid: float | None
    edge_bps: float | None
    signal: str           # SPIKE_UP / DIP_DOWN / NEUTRAL
    mode: Mode
    sigma_bps: float | None
    data_quality: str


def ema(prices: list[float], alpha: float) -> float | None:
    if not prices:
        return None
    alpha = min(1.0, max(0.0, alpha))
    value = prices[0]
    for px in prices[1:]:
        value = alpha * px + (1.0 - alpha) * value
    return value


def _sigma_bps(prices: list[float]) -> float | None:
    if len(prices) < 3:
        return None
    rets = [
        math.log(prices[i] / prices[i - 1])
        for i in range(1, len(prices))
        if prices[i - 1] > 0 and prices[i] > 0
    ]
    if len(rets) < 2:
        return None
    mean = sum(rets) / len(rets)
    var = sum((r - mean) ** 2 for r in rets) / (len(rets) - 1)
    return math.sqrt(var) * 10_000.0


def compute_fair_value(
    prices: list[Any] | None,
    *,
    mode: Mode = "smooth",
    fast_alpha: float = 0.5,
    smooth_alpha: float = 0.15,
    spike_k: float = 2.0,
) -> FairValue:
    """Compute fair value, edge vs latest mid, and spike/dip flag.

    ``prices`` is an oldest->newest series of mids (real data only).
    """
    if not prices:
        return FairValue(None, None, None, "NEUTRAL", mode, None, "MISSING")
    clean = [p for p in (safe_float(x) for x in prices) if p is not None and p > 0]
    if len(clean) < 3:
        return FairValue(None, None, None, "NEUTRAL", mode, None, "DEGRADED")

    alpha = fast_alpha if mode == "fast" else smooth_alpha
    fair = ema(clean, alpha)
    mid = clean[-1]
    sigma = _sigma_bps(clean)
    if fair is None or fair <= 0:
        return FairValue(None, mid, None, "NEUTRAL", mode, sigma, "DEGRADED")

    edge_bps = (fair - mid) / mid * 10_000.0
    move_bps = (clean[-1] - clean[-2]) / clean[-2] * 10_000.0 if clean[-2] > 0 else 0.0

    signal = "NEUTRAL"
    if sigma is not None and sigma > 0:
        if move_bps >= spike_k * sigma:
            signal = "SPIKE_UP"
        elif move_bps <= -spike_k * sigma:
            signal = "DIP_DOWN"

    return FairValue(
        fair_value=fair,
        mid=mid,
        edge_bps=edge_bps,
        signal=signal,
        mode=mode,
        sigma_bps=sigma,
        data_quality="OK",
    )
