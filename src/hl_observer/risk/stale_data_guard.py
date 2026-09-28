from __future__ import annotations

import math


def data_fresh(signal_age_ms: int, max_signal_age_ms: int) -> bool:
    """Return true only for finite, non-negative ages within a finite budget."""
    try:
        age = float(signal_age_ms)
        limit = float(max_signal_age_ms)
    except (TypeError, ValueError):
        return False
    return math.isfinite(age) and math.isfinite(limit) and age >= 0.0 and limit >= 0.0 and age <= limit
