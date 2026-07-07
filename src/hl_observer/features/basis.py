"""V13 #154 — perp vs oracle/index basis + oracle lag (mlmodelpoly/polyrec)."""

from __future__ import annotations


def basis_bps(perp_price: float, oracle_price: float) -> float:
    """Signed basis in bps: + = perp richer than oracle, - = perp cheaper."""
    o = float(oracle_price)
    if o <= 0.0:
        return 0.0
    return round((float(perp_price) - o) / o * 10_000.0, 4)


def oracle_lag_ms(perp_ts_ms: int, oracle_ts_ms: int) -> int:
    """How stale the oracle is vs the perp tick (>=0)."""
    return max(0, int(perp_ts_ms) - int(oracle_ts_ms))


__all__ = ["basis_bps", "oracle_lag_ms"]
