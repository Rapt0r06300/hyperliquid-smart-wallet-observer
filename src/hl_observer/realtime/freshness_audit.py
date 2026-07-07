"""V14 #166 — End-to-end FRESHNESS audit (per-stage latency + age histogram).

The single ``signal_age_ms`` number hides *where* the delay accrues. This module
breaks freshness into **stages** (e.g. exchange->recv "capture", recv->decision
"compute", and the total) and produces an **age histogram** so we can see whether
signals land in the ultra-hot few-second window or arrive already stale.

Pure / read-only: it only summarises numbers already measured locally. No network,
no order, no fabrication. Safe to call anywhere; degrades to empty when no data.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable, Sequence


# Hot->stale bucket edges (ms). The copy edge lives in the first 1-4 s.
DEFAULT_AGE_BUCKET_EDGES_MS: tuple[int, ...] = (1_000, 2_000, 4_000, 8_000, 15_000, 30_000)


def _percentile(sorted_vals: Sequence[float], q: float) -> float | None:
    if not sorted_vals:
        return None
    if len(sorted_vals) == 1:
        return float(sorted_vals[0])
    idx = min(len(sorted_vals) - 1, max(0, int(round((len(sorted_vals) - 1) * q))))
    return float(sorted_vals[idx])


@dataclass(frozen=True, slots=True)
class StageLatency:
    name: str
    samples: int
    min_ms: float | None
    p50_ms: float | None
    avg_ms: float | None
    p95_ms: float | None
    max_ms: float | None


def build_stage_latency(name: str, values_ms: Iterable[float]) -> StageLatency:
    vals = sorted(float(v) for v in values_ms if v is not None)
    if not vals:
        return StageLatency(name, 0, None, None, None, None, None)
    return StageLatency(
        name=name,
        samples=len(vals),
        min_ms=vals[0],
        p50_ms=_percentile(vals, 0.50),
        avg_ms=round(sum(vals) / len(vals), 3),
        p95_ms=_percentile(vals, 0.95),
        max_ms=vals[-1],
    )


@dataclass(frozen=True, slots=True)
class HistogramBucket:
    label: str
    lo_ms: float
    hi_ms: float | None  # None = open-ended (overflow)
    count: int


@dataclass(frozen=True, slots=True)
class AgeHistogram:
    total: int
    buckets: tuple[HistogramBucket, ...]
    stale_threshold_ms: int
    stale_count: int
    stale_ratio: float | None
    fresh_count: int            # ages <= first bucket edge (ultra-hot)
    fresh_ratio: float | None


def build_age_histogram(
    ages_ms: Iterable[float],
    *,
    bucket_edges_ms: Sequence[int] = DEFAULT_AGE_BUCKET_EDGES_MS,
    stale_threshold_ms: int = 15_000,
) -> AgeHistogram:
    ages = [float(a) for a in ages_ms if a is not None]
    edges = sorted(int(e) for e in bucket_edges_ms)
    counts = [0 for _ in range(len(edges) + 1)]
    for a in ages:
        placed = False
        for i, edge in enumerate(edges):
            if a <= edge:
                counts[i] += 1
                placed = True
                break
        if not placed:
            counts[-1] += 1
    buckets: list[HistogramBucket] = []
    lo = 0.0
    for i, edge in enumerate(edges):
        buckets.append(HistogramBucket(f"<={edge}ms", lo, float(edge), counts[i]))
        lo = float(edge)
    buckets.append(HistogramBucket(f">{edges[-1]}ms" if edges else "all", lo, None, counts[-1]))
    total = len(ages)
    stale = sum(1 for a in ages if a > stale_threshold_ms)
    fresh = sum(1 for a in ages if edges and a <= edges[0])
    return AgeHistogram(
        total=total,
        buckets=tuple(buckets),
        stale_threshold_ms=int(stale_threshold_ms),
        stale_count=stale,
        stale_ratio=round(stale / total, 6) if total else None,
        fresh_count=fresh,
        fresh_ratio=round(fresh / total, 6) if total else None,
    )


@dataclass(frozen=True, slots=True)
class FreshnessAudit:
    stages: tuple[StageLatency, ...]
    histogram: AgeHistogram
    status: str
    samples: int = field(default=0)


def build_freshness_audit(
    *,
    stage_samples: dict[str, Iterable[float]] | None = None,
    total_age_ms: Iterable[float],
    bucket_edges_ms: Sequence[int] = DEFAULT_AGE_BUCKET_EDGES_MS,
    stale_threshold_ms: int = 15_000,
) -> FreshnessAudit:
    """Per-stage latency summaries + an age histogram on the end-to-end signal age.

    ``stage_samples`` maps a stage name -> latency values for that stage (optional).
    ``total_age_ms`` is the end-to-end signal age used for the histogram + status.
    """
    stages: list[StageLatency] = []
    for name, values in (stage_samples or {}).items():
        stages.append(build_stage_latency(name, values))
    total_list = [float(a) for a in total_age_ms if a is not None]
    stages.append(build_stage_latency("total", total_list))
    hist = build_age_histogram(total_list, bucket_edges_ms=bucket_edges_ms, stale_threshold_ms=stale_threshold_ms)
    if hist.total == 0:
        status = "NO_SIGNAL_AGE_DATA"
    elif hist.stale_ratio is not None and hist.stale_ratio > 0.5:
        status = "MOSTLY_STALE"
    elif hist.stale_count > 0:
        status = "SOME_STALE"
    else:
        status = "OK"
    return FreshnessAudit(stages=tuple(stages), histogram=hist, status=status, samples=hist.total)


def _stage_samples_from_events(events: Sequence[object]) -> tuple[dict[str, list[float]], list[float]]:
    """Derive per-stage latencies from decision events when timestamps are present.

    Recognised optional attributes (ms epoch): ``exchange_ts_ms`` (leader fill at the
    exchange), ``recv_ts_ms`` (when we received it), ``decision_ts_ms`` (when we decided).
    Falls back to ``signal_age_ms`` for the total. Any missing piece is skipped.
    """
    capture: list[float] = []   # exchange -> recv
    compute: list[float] = []   # recv -> decision
    total: list[float] = []
    for ev in events:
        ex = getattr(ev, "exchange_ts_ms", None)
        rc = getattr(ev, "recv_ts_ms", None)
        dc = getattr(ev, "decision_ts_ms", None)
        if ex is not None and rc is not None and rc >= ex:
            capture.append(float(rc) - float(ex))
        if rc is not None and dc is not None and dc >= rc:
            compute.append(float(dc) - float(rc))
        age = getattr(ev, "signal_age_ms", None)
        if age is not None:
            total.append(float(age))
        elif ex is not None and dc is not None and dc >= ex:
            total.append(float(dc) - float(ex))
    stages: dict[str, list[float]] = {}
    if capture:
        stages["capture_exchange_to_recv"] = capture
    if compute:
        stages["compute_recv_to_decision"] = compute
    return stages, total


def build_freshness_audit_from_events(
    events: Sequence[object],
    *,
    stale_threshold_ms: int = 15_000,
) -> FreshnessAudit:
    stages, total = _stage_samples_from_events(events)
    return build_freshness_audit(stage_samples=stages, total_age_ms=total, stale_threshold_ms=stale_threshold_ms)


def build_freshness_audit_from_logs(log_dir: Path, *, stale_threshold_ms: int = 15_000) -> FreshnessAudit:
    """Convenience: load local decision events and audit their freshness. Guarded."""
    try:
        from hl_observer.simulation.decision_replay_analyzer import load_decision_events
        events = list(load_decision_events(Path(log_dir)))
    except Exception:
        events = []
    return build_freshness_audit_from_events(events, stale_threshold_ms=stale_threshold_ms)


def format_freshness_audit(audit: FreshnessAudit) -> str:
    lines = [
        "freshness_audit=local_logs_only",
        f"status={audit.status}",
        f"samples={audit.samples}",
        "stages:",
    ]
    for st in audit.stages:
        lines.append(
            f"- {st.name}: n={st.samples} min={st.min_ms} p50={st.p50_ms} avg={st.avg_ms} p95={st.p95_ms} max={st.max_ms}"
        )
    h = audit.histogram
    lines.append(f"histogram (stale>{h.stale_threshold_ms}ms ratio={h.stale_ratio} fresh_ratio={h.fresh_ratio}):")
    for b in h.buckets:
        lines.append(f"- {b.label}: {b.count}")
    lines.append("execution=forbidden")
    lines.append("paper_local_only=true")
    return "\n".join(lines)


__all__ = [
    "DEFAULT_AGE_BUCKET_EDGES_MS",
    "StageLatency",
    "build_stage_latency",
    "HistogramBucket",
    "AgeHistogram",
    "build_age_histogram",
    "FreshnessAudit",
    "build_freshness_audit",
    "build_freshness_audit_from_events",
    "build_freshness_audit_from_logs",
    "format_freshness_audit",
]
