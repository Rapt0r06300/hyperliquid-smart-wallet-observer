from __future__ import annotations

from datetime import datetime, timedelta


def simulated_latency_ms(default_ms: int = 250) -> int:
    return max(0, default_ms)


def simulate_latency_timestamp(base_timestamp: datetime, latency_ms: int) -> datetime:
    if latency_ms < 0:
        raise ValueError("latency_ms must be non-negative")
    return base_timestamp + timedelta(milliseconds=latency_ms)
