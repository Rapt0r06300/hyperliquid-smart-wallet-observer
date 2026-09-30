from __future__ import annotations

import math


def copy_delay_decay(raw_edge: float, *, delay_ms: int, half_life_ms: int) -> float:
    if half_life_ms <= 0:
        return 0.0
    return raw_edge * math.exp(-delay_ms / half_life_ms)
