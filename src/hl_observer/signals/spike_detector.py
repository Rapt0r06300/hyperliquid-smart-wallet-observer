"""V15 #190 — 5-second spike detector (z-score) for entry timing.

Flags a statistically unusual short-window move (|z| >= threshold) so we time entries to
real impulses, not noise. Pure; needs >= min_samples to speak (else NO_DATA, never a spike).
"""

from __future__ import annotations

from dataclasses import dataclass
from statistics import fmean, pstdev
from typing import Sequence


@dataclass(frozen=True, slots=True)
class SpikeResult:
    z: float | None
    is_spike: bool
    direction: str          # UP | DOWN | NONE
    status: str             # OK | NO_DATA


def detect_spike(
    recent_returns_bps: Sequence[float],
    *,
    z_threshold: float = 2.0,
    min_samples: int = 5,
) -> SpikeResult:
    vals = [float(x) for x in recent_returns_bps]
    if len(vals) < max(2, int(min_samples)):
        return SpikeResult(None, False, "NONE", "NO_DATA")
    mu = fmean(vals)
    sd = pstdev(vals)
    last = vals[-1]
    if sd <= 1e-9:
        z = 0.0
    else:
        z = (last - mu) / sd
    is_spike = abs(z) >= float(z_threshold)
    direction = "UP" if (is_spike and z > 0) else ("DOWN" if is_spike else "NONE")
    return SpikeResult(round(z, 6), is_spike, direction, "OK")


__all__ = ["SpikeResult", "detect_spike"]
