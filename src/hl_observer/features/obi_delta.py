"""V15 #191 — OBI-delta: change in order-book imbalance over 10s / 30s windows.

A rising imbalance (toward our side) is a stronger confirmation than a static one. Pure:
takes timestamped OBI samples and reports the delta over each window + whether it confirms a side.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Sequence


@dataclass(frozen=True, slots=True)
class ObiDeltaResult:
    deltas_by_window_ms: dict
    confirms_side: str | None       # LONG | SHORT | None
    latest_obi: float | None


def _obi_at_or_before(samples: Sequence[tuple[int, float]], target_ms: int) -> float | None:
    chosen: float | None = None
    for ts, obi in samples:
        if int(ts) <= target_ms:
            chosen = float(obi)
        else:
            break
    return chosen


def obi_delta(
    samples: Sequence[tuple[int, float]],
    *,
    now_ms: int,
    windows_ms: Sequence[int] = (10_000, 30_000),
    confirm_threshold: float = 0.1,
) -> ObiDeltaResult:
    """samples: ascending (ts_ms, obi in [-1,1]). Delta = latest - obi ~window ago."""
    s = sorted(((int(t), float(o)) for t, o in samples), key=lambda r: r[0])
    if not s:
        return ObiDeltaResult({}, None, None)
    latest = s[-1][1]
    deltas: dict[int, float | None] = {}
    for w in windows_ms:
        past = _obi_at_or_before(s, int(now_ms) - int(w))
        deltas[int(w)] = None if past is None else round(latest - past, 6)
    # confirmation: shortest window delta beyond threshold
    first_w = sorted(windows_ms)[0]
    d0 = deltas.get(int(first_w))
    confirms: str | None = None
    if d0 is not None:
        if d0 >= confirm_threshold:
            confirms = "LONG"
        elif d0 <= -confirm_threshold:
            confirms = "SHORT"
    return ObiDeltaResult(deltas, confirms, round(latest, 6))


__all__ = ["ObiDeltaResult", "obi_delta"]
