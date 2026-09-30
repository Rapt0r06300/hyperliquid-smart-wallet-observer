from __future__ import annotations


def wallet_degraded(recent_expectancy_bps: float, min_recent_expectancy_bps: float = 0.0) -> bool:
    return recent_expectancy_bps < min_recent_expectancy_bps
