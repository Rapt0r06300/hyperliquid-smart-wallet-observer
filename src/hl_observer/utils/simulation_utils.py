from __future__ import annotations

from typing import Any

def calculate_gross_pnl(side: str, entry_price: float, exit_price: float, size: float) -> float:
    """Standardized gross PnL calculation."""
    if side.upper() == "LONG":
        return (exit_price - entry_price) * size
    elif side.upper() == "SHORT":
        return (entry_price - exit_price) * size
    return 0.0

def calculate_net_pnl(gross_pnl: float, exit_fee: float, allocated_entry_fee: float = 0.0) -> float:
    """Standardized net PnL calculation subtracting fees."""
    return gross_pnl - exit_fee - allocated_entry_fee

def get_exit_price(base_price: float, side: str, spread_bps: float, slippage_bps: float) -> float:
    """Apply spread and slippage to get simulation exit price."""
    penalty = (spread_bps + slippage_bps) / 10_000.0
    # To exit a LONG (selling), we get a lower price
    if side.upper() == "LONG":
        return base_price * (1.0 - penalty)
    # To exit a SHORT (buying back), we pay a higher price
    else:
        return base_price * (1.0 + penalty)

def get_entry_price(base_price: float, side: str, spread_bps: float, slippage_bps: float) -> float:
    """Apply spread and slippage to get simulation entry price."""
    penalty = (spread_bps + slippage_bps) / 10_000.0
    # To enter a LONG (buying), we pay a higher price
    if side.upper() == "LONG":
        return base_price * (1.0 + penalty)
    # To enter a SHORT (selling), we get a lower price
    else:
        return base_price * (1.0 - penalty)
