from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from hl_observer.simulation.decision_replay_analyzer import load_decision_events


@dataclass(frozen=True, slots=True)
class LatencyReport:
    source_dir: Path
    samples: int
    min_ms: int | None
    avg_ms: float | None
    p95_ms: int | None
    max_ms: int | None
    stale_over_3000ms: int
    status: str


def build_latency_report(log_dir: Path, *, stale_threshold_ms: int = 3_000) -> LatencyReport:
    events = load_decision_events(log_dir)
    ages = sorted(int(event.signal_age_ms) for event in events if event.signal_age_ms is not None)
    if not ages:
        return LatencyReport(log_dir, 0, None, None, None, None, 0, "NO_SIGNAL_AGE_DATA")
    stale = sum(1 for age in ages if age > stale_threshold_ms)
    p95_index = min(len(ages) - 1, int(round((len(ages) - 1) * 0.95)))
    status = "OK" if stale == 0 else "STALE_SIGNALS_PRESENT"
    return LatencyReport(
        source_dir=log_dir,
        samples=len(ages),
        min_ms=ages[0],
        avg_ms=round(sum(ages) / len(ages), 3),
        p95_ms=ages[p95_index],
        max_ms=ages[-1],
        stale_over_3000ms=stale,
        status=status,
    )


def format_latency_report(report: LatencyReport) -> str:
    return "\n".join(
        [
            "realtime_latency_report=local_logs_only",
            f"source_dir={report.source_dir}",
            f"samples={report.samples}",
            f"min_ms={report.min_ms}",
            f"avg_ms={report.avg_ms}",
            f"p95_ms={report.p95_ms}",
            f"max_ms={report.max_ms}",
            f"stale_over_3000ms={report.stale_over_3000ms}",
            f"status={report.status}",
        ]
    )

