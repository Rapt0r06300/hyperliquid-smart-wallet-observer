"""V15 #187 — Anchored VWAP (AVWAP) + cheap/expensive deviation trigger."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence


def anchored_vwap(prices: Sequence[float], volumes: Sequence[float]) -> float | None:
    """Volume-weighted average price since the anchor. None if no volume."""
    num = 0.0
    den = 0.0
    for p, v in zip(prices, volumes):
        vv = max(0.0, float(v))
        num += float(p) * vv
        den += vv
    if den <= 0.0:
        return None
    return num / den


@dataclass(frozen=True, slots=True)
class AvwapDeviation:
    avwap: float | None
    deviation_bps: float | None     # +ve = price above AVWAP (expensive), -ve = below (cheap)
    trigger: str                    # CHEAP | EXPENSIVE | NEUTRAL | NO_DATA


def avwap_deviation(
    *,
    price: float,
    prices: Sequence[float],
    volumes: Sequence[float],
    threshold_bps: float = 25.0,
) -> AvwapDeviation:
    av = anchored_vwap(prices, volumes)
    if av is None or av <= 0.0:
        return AvwapDeviation(av, None, "NO_DATA")
    dev = (float(price) - av) / av * 10_000.0
    if dev <= -threshold_bps:
        trig = "CHEAP"
    elif dev >= threshold_bps:
        trig = "EXPENSIVE"
    else:
        trig = "NEUTRAL"
    return AvwapDeviation(round(av, 8), round(dev, 4), trig)


__all__ = ["anchored_vwap", "AvwapDeviation", "avwap_deviation"]
