from __future__ import annotations


def calculate_net_pnl(trades: list[float]) -> float | None:
    if not trades:
        return None
    return float(sum(trades))


def calculate_gross_pnl(pnl_values: list[float]) -> float | None:
    if not pnl_values:
        return None
    return float(sum(pnl_values))


def calculate_total_fees(fees: list[float]) -> float:
    return float(sum(value for value in fees if value >= 0))


def calculate_net_pnl_after_fees(pnl_values: list[float], fees: list[float]) -> float | None:
    gross = calculate_gross_pnl(pnl_values)
    if gross is None:
        return None
    return gross - calculate_total_fees(fees)
