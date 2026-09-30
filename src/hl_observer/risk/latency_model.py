from __future__ import annotations


def latency_penalty_bps(*, signal_age_ms: int, bps_per_second: float = 5.0) -> float:
    return max(0.0, signal_age_ms / 1000.0 * bps_per_second)
