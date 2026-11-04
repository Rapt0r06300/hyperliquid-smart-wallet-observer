from __future__ import annotations

import math

from hl_observer.edge.signal_decay import decay_edge


def latency_decay_bps(raw_edge_bps: float, latency_ms: int, half_life_ms: int) -> float:
    return raw_edge_bps - decay_edge(raw_edge_bps, latency_ms, half_life_ms)


def latency_stress_receipt(latencies_ms: list[float | int], *, min_samples: int = 2) -> dict[str, object]:
    """Stress paper latency with observed p95/p99 rather than an optimistic constant."""
    if isinstance(min_samples, bool) or not isinstance(min_samples, int) or min_samples < 2:
        return {"status": "UNMEASURABLE", "reason": "invalid_min_samples"}
    if not isinstance(latencies_ms, list) or len(latencies_ms) < min_samples:
        return {"status": "MORE_DATA", "reason": "latency_sample_insufficient"}
    values = []
    for value in latencies_ms:
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(float(value)) or value < 0:
            return {"status": "UNMEASURABLE", "reason": "invalid_latency_sample"}
        values.append(float(value))
    values.sort()
    def quantile(q: float) -> float:
        return round(values[max(0, min(len(values) - 1, math.ceil(q * len(values)) - 1))], 6)
    return {"status": "PROVEN", "count": len(values), "p95_ms": quantile(0.95),
            "p99_ms": quantile(0.99), "stress_ms": quantile(0.99),
            "optimistic_constant_used": False}
