from __future__ import annotations


def slippage_ok(estimated_slippage_bps: float, max_slippage_bps: float) -> bool:
    return estimated_slippage_bps <= max_slippage_bps
