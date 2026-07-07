"""Fee model for triangular/path arbitrage."""

from __future__ import annotations


def path_fee_bps(hops: int, *, fee_bps_per_hop: float) -> float:
    return round(max(0, int(hops)) * float(fee_bps_per_hop), 8)


__all__ = ["path_fee_bps"]
