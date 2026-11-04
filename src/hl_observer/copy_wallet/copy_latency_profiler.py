"""Latency profiler for local paper copy decisions."""

from __future__ import annotations

from dataclasses import dataclass
from statistics import median
from typing import Iterable


@dataclass(frozen=True, slots=True)
class LatencyProfile:
    count: int
    min_ms: int
    p50_ms: int
    max_ms: int
    stale_count: int


def profile_copy_latency(latencies_ms: Iterable[int], *, stale_threshold_ms: int = 5_000) -> LatencyProfile:
    vals = sorted(max(0, int(x)) for x in latencies_ms)
    if not vals:
        return LatencyProfile(0, 0, 0, 0, 0)
    return LatencyProfile(
        count=len(vals),
        min_ms=vals[0],
        p50_ms=int(median(vals)),
        max_ms=vals[-1],
        stale_count=sum(1 for x in vals if x > int(stale_threshold_ms)),
    )


def decision_after_receive_receipt(*, received_at_ms: int, decision_at_ms: int) -> dict[str, object]:
    """Prove the decision clock never precedes the local receive clock."""
    if any(isinstance(value, bool) or not isinstance(value, int) for value in (received_at_ms, decision_at_ms)):
        return {"status": "UNMEASURABLE", "reason": "timestamps_must_be_integers"}
    if received_at_ms < 0 or decision_at_ms < 0:
        return {"status": "UNMEASURABLE", "reason": "timestamps_must_be_non_negative"}
    if decision_at_ms < received_at_ms:
        return {"status": "UNMEASURABLE", "reason": "decision_before_receive"}
    return {"status": "PROVEN", "received_at_ms": received_at_ms, "decision_at_ms": decision_at_ms,
            "queue_latency_ms": decision_at_ms - received_at_ms}


__all__ = ["LatencyProfile", "profile_copy_latency", "decision_after_receive_receipt"]
