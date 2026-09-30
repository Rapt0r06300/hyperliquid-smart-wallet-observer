"""V15 #208 — Read-only observability metrics (lag, throughput, errors, reconnects, fills/s).

Pure builder + Prometheus-style text formatter for a /metrics view. It only summarises
counters the runtime already tracks; it performs no action. read-only / paper-only.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True, slots=True)
class ObservabilityMetrics:
    lag_ms: float
    throughput_msg_per_s: float
    fills_per_s: float
    errors: int
    reconnects: int
    open_positions: int
    decisions_total: int
    accepts_total: int


def build_metrics(
    *,
    lag_ms: float = 0.0,
    messages: int = 0,
    fills: int = 0,
    elapsed_s: float = 1.0,
    errors: int = 0,
    reconnects: int = 0,
    open_positions: int = 0,
    decisions_total: int = 0,
    accepts_total: int = 0,
) -> ObservabilityMetrics:
    el = max(1e-9, float(elapsed_s))
    return ObservabilityMetrics(
        lag_ms=round(float(lag_ms), 3),
        throughput_msg_per_s=round(float(messages) / el, 3),
        fills_per_s=round(float(fills) / el, 3),
        errors=int(errors),
        reconnects=int(reconnects),
        open_positions=int(open_positions),
        decisions_total=int(decisions_total),
        accepts_total=int(accepts_total),
    )


def format_metrics_prometheus(m: ObservabilityMetrics, *, prefix: str = "hypersmart") -> str:
    lines = [
        f"{prefix}_lag_ms {m.lag_ms}",
        f"{prefix}_throughput_msg_per_s {m.throughput_msg_per_s}",
        f"{prefix}_fills_per_s {m.fills_per_s}",
        f"{prefix}_errors_total {m.errors}",
        f"{prefix}_reconnects_total {m.reconnects}",
        f"{prefix}_open_positions {m.open_positions}",
        f"{prefix}_decisions_total {m.decisions_total}",
        f"{prefix}_accepts_total {m.accepts_total}",
        f"{prefix}_execution_forbidden 1",
        f"{prefix}_paper_local_only 1",
    ]
    return "\n".join(lines) + "\n"


__all__ = ["ObservabilityMetrics", "build_metrics", "format_metrics_prometheus"]
