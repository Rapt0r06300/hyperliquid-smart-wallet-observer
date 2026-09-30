"""Execution realism primitives for paper-only backtests."""
from __future__ import annotations

import math


def _finite_non_negative(*values: float) -> bool:
    return all(
        not isinstance(value, bool)
        and math.isfinite(float(value))
        and float(value) >= 0.0
        for value in values
    )


def maker_fill_probability(
    *, queue_ahead_notional: float, incoming_flow_notional: float, base: float = 0.9
) -> float:
    if not _finite_non_negative(queue_ahead_notional, incoming_flow_notional, base):
        raise ValueError("fill inputs must be finite and non-negative")
    if not 0.0 <= float(base) <= 1.0:
        raise ValueError("base must be in [0, 1]")
    queue = float(queue_ahead_notional)
    flow = float(incoming_flow_notional)
    if flow <= 0:
        return 0.0
    return round(max(0.0, min(1.0, float(base) * flow / (queue + flow))), 6)


def adverse_selection_penalty_bps(
    volatility_bps: float, *, toxicity: float = 0.5
) -> float:
    if not _finite_non_negative(volatility_bps, toxicity):
        raise ValueError("adverse selection inputs must be finite and non-negative")
    return round(float(volatility_bps) * float(toxicity), 6)


def latency_jitter_ms(
    base_ms: float, *, jitter_frac: float = 0.3, sample: float = 0.5
) -> float:
    if (
        not _finite_non_negative(base_ms, jitter_frac)
        or isinstance(sample, bool)
        or not math.isfinite(float(sample))
        or not 0.0 <= float(sample) <= 1.0
    ):
        raise ValueError("latency jitter inputs are invalid")
    return round(
        float(base_ms)
        * (1.0 + float(jitter_frac) * (2.0 * float(sample) - 1.0)),
        3,
    )


__all__ = [
    "maker_fill_probability",
    "adverse_selection_penalty_bps",
    "latency_jitter_ms",
]
