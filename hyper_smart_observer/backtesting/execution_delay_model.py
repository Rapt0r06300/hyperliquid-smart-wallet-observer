from __future__ import annotations


def delay_penalty_bps(delay_ms: int, *, bps_per_second: float = 1.0) -> float:
    if delay_ms < 0:
        raise ValueError("delay_ms must be non-negative")
    return (delay_ms / 1000.0) * bps_per_second
