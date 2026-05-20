from __future__ import annotations


def exit_capture_ratio(realized_profit_bps: float, mfe_bps: float) -> float:
    if mfe_bps <= 0:
        return 0.0
    return realized_profit_bps / mfe_bps


def profit_giveback_bps(realized_profit_bps: float, mfe_bps: float) -> float:
    return max(0.0, mfe_bps - realized_profit_bps)
