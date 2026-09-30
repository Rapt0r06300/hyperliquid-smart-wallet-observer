"""V14 #169 — Clock-offset correction for an EXACT signal age.

If our local clock differs from the exchange clock, ``local_now - exchange_ts`` is a
biased measure of how stale a signal is. This module estimates the offset honestly:

* **NTP-style** (preferred): from round-trip samples (t0 local send, t_server, t1
  local recv) it computes per-sample offset theta = ((t_server - t0) + (t_server - t1))/2
  and delay = t1 - t0, then reports the median theta with uncertainty ~ min_delay/2.
* **one-way lower bound** (fallback/diagnostic): from (server_send, local_recv) pairs
  it can only bound the offset; it is reported as such and NOT used to *inflate*
  freshness (we never under-state staleness on a guess).

Convention: ``server_ts ~= local_ts + offset_ms`` (offset = server - local).
Pure / read-only: no network here; the caller supplies measured timestamps.
"""

from __future__ import annotations

from dataclasses import dataclass
from statistics import median
from typing import Sequence


@dataclass(frozen=True, slots=True)
class ClockSample:
    t0_local_send_ms: float
    t_server_ms: float
    t1_local_recv_ms: float


@dataclass(frozen=True, slots=True)
class ClockOffsetEstimate:
    offset_ms: float           # server - local (add to local to get server time)
    uncertainty_ms: float      # ~ half of the best round-trip delay
    delay_ms: float | None     # best (minimum) observed round-trip delay
    samples: int
    method: str                # "ntp" | "one_way_lower_bound" | "none"
    trusted: bool              # whether it is safe to use for age correction


def estimate_clock_offset(samples: Sequence[ClockSample]) -> ClockOffsetEstimate:
    """NTP-style estimate. Picks the offset from the lowest-delay samples (most accurate)."""
    rows = []
    for s in samples:
        delay = float(s.t1_local_recv_ms) - float(s.t0_local_send_ms)
        if delay < 0:
            continue
        theta = ((float(s.t_server_ms) - float(s.t0_local_send_ms)) + (float(s.t_server_ms) - float(s.t1_local_recv_ms))) / 2.0
        rows.append((delay, theta))
    if not rows:
        return ClockOffsetEstimate(0.0, 0.0, None, 0, "none", False)
    rows.sort(key=lambda r: r[0])
    best_delay = rows[0][0]
    # Use the offsets from the lowest-delay third (min 1) for a robust, low-noise estimate.
    k = max(1, len(rows) // 3)
    thetas = [r[1] for r in rows[:k]]
    offset = float(median(thetas))
    return ClockOffsetEstimate(
        offset_ms=round(offset, 3),
        uncertainty_ms=round(best_delay / 2.0, 3),
        delay_ms=round(best_delay, 3),
        samples=len(rows),
        method="ntp",
        trusted=True,
    )


def estimate_offset_one_way(pairs: Sequence[tuple[float, float]]) -> ClockOffsetEstimate:
    """Lower-bound estimate from (server_send_ms, local_recv_ms) pairs.

    ``local_recv - server_send = (local - server) + transit = -offset + transit``.
    The minimum observed value approaches ``-offset`` only when transit -> 0, so it is a
    bound, not a point estimate. Reported as untrusted; do not use to inflate freshness.
    """
    diffs = [float(local_recv) - float(server_send) for server_send, local_recv in pairs]
    if not diffs:
        return ClockOffsetEstimate(0.0, 0.0, None, 0, "none", False)
    floor = min(diffs)
    spread = max(diffs) - floor
    # floor ~= -offset + min_transit  =>  offset ~= -floor (minus a positive transit term).
    return ClockOffsetEstimate(
        offset_ms=round(-floor, 3),
        uncertainty_ms=round(spread, 3),
        delay_ms=None,
        samples=len(diffs),
        method="one_way_lower_bound",
        trusted=False,
    )


def corrected_signal_age_ms(
    *,
    local_now_ms: float,
    server_event_ms: float,
    estimate: ClockOffsetEstimate | None = None,
    clamp_non_negative: bool = True,
) -> float:
    """Age corrected for clock offset.

    raw age = local_now - server_event. With ``server ~= local + offset``, the event's
    local-equivalent time is ``server_event - offset``; corrected age = local_now -
    (server_event - offset) = raw_age + offset. We only apply a *trusted* estimate.
    """
    raw = float(local_now_ms) - float(server_event_ms)
    if estimate is not None and estimate.trusted and estimate.method == "ntp":
        raw = raw + float(estimate.offset_ms)
    if clamp_non_negative and raw < 0:
        return 0.0
    return round(raw, 3)


def format_clock_offset(estimate: ClockOffsetEstimate) -> str:
    return "\n".join(
        [
            "clock_offset_estimate=local_measurement_only",
            f"method={estimate.method}",
            f"offset_ms={estimate.offset_ms}",
            f"uncertainty_ms={estimate.uncertainty_ms}",
            f"delay_ms={estimate.delay_ms}",
            f"samples={estimate.samples}",
            f"trusted={str(estimate.trusted).lower()}",
        ]
    )


__all__ = [
    "ClockSample",
    "ClockOffsetEstimate",
    "estimate_clock_offset",
    "estimate_offset_one_way",
    "corrected_signal_age_ms",
    "format_clock_offset",
]
