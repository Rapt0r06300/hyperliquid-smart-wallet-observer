from __future__ import annotations

import math


def decay_edge(raw_edge_bps: float, signal_age_ms: int, half_life_ms: int) -> float:
    if half_life_ms <= 0:
        raise ValueError("half_life_ms must be positive")
    if signal_age_ms < 0:
        raise ValueError("signal_age_ms cannot be negative")
    return raw_edge_bps * math.exp(-signal_age_ms / half_life_ms)


def is_late_signal(signal_age_ms: int, max_signal_age_ms: int) -> bool:
    return signal_age_ms > max_signal_age_ms
