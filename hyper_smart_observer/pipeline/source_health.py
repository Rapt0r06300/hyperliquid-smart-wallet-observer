"""Phase 11: uniform SourceHealth model for every read-only endpoint/channel.

Pure data + deterministic builder. Used to surface OK/DEGRADED/FAIL with latency,
staleness, retry budget and a raw reference so the scanner, DecisionLedger,
dashboard, exports and backtests all describe source quality the same way.
No network, no execution.
"""

from __future__ import annotations

from dataclasses import dataclass

STATUS_OK = "OK"
STATUS_DEGRADED = "DEGRADED"
STATUS_FAIL = "FAIL"


@dataclass(frozen=True)
class SourceHealth:
    name: str
    status: str
    latency_ms: float | None = None
    source_ts: int | None = None
    local_received_ts: int | None = None
    staleness_ms: int | None = None
    retry_count: int = 0
    rate_budget: float | None = None
    degraded_reason: str | None = None
    raw_ref: str | None = None


def build_source_health(
    name: str,
    *,
    ok: bool = True,
    source_ts: int | None = None,
    local_received_ts: int | None = None,
    latency_ms: float | None = None,
    retry_count: int = 0,
    rate_budget: float | None = None,
    degraded_reason: str | None = None,
    raw_ref: str | None = None,
    max_staleness_ms: int = 10_000,
) -> SourceHealth:
    staleness = None
    if source_ts is not None and local_received_ts is not None:
        staleness = int(local_received_ts - source_ts)

    if not ok:
        status = STATUS_FAIL
        degraded_reason = degraded_reason or "source unavailable"
    elif degraded_reason or (staleness is not None and staleness > max_staleness_ms):
        status = STATUS_DEGRADED
        if degraded_reason is None:
            degraded_reason = f"stale {staleness}ms > {max_staleness_ms}ms"
    else:
        status = STATUS_OK

    return SourceHealth(
        name=name,
        status=status,
        latency_ms=latency_ms,
        source_ts=source_ts,
        local_received_ts=local_received_ts,
        staleness_ms=staleness,
        retry_count=retry_count,
        rate_budget=rate_budget,
        degraded_reason=degraded_reason,
        raw_ref=raw_ref,
    )
