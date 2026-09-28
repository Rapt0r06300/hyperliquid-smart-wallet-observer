from __future__ import annotations

import math


def slippage_ok(estimated_slippage_bps: float, max_slippage_bps: float) -> bool:
    """Fail closed when an execution-cost estimate is absent or non-finite."""
    try:
        estimated = float(estimated_slippage_bps)
        maximum = float(max_slippage_bps)
    except (TypeError, ValueError):
        return False
    return math.isfinite(estimated) and math.isfinite(maximum) and estimated >= 0.0 and maximum >= 0.0 and estimated <= maximum
