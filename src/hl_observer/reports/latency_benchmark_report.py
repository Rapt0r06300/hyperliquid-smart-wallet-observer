"""Latency report for copy path diagnostics."""

from __future__ import annotations

from dataclasses import asdict
from statistics import median

from hl_observer.copy_mode.copy_latency_profiler import CopyLatencyProfile


def build_latency_benchmark_report(profiles: list[CopyLatencyProfile]) -> dict[str, object]:
    totals = [item.total_ms for item in profiles if item.total_ms is not None]
    warnings = [item.warning for item in profiles if item.warning]
    return {
        "samples": len(profiles),
        "median_total_ms": median(totals) if totals else None,
        "max_total_ms": max(totals) if totals else None,
        "warning_count": len(warnings),
        "warnings": sorted(set(warnings)),
        "profiles": [asdict(item) for item in profiles[:100]],
        "paper_only": True,
        "external_action": False,
    }


__all__ = ["build_latency_benchmark_report"]
