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

def calculate_dynamic_slippage_bps(notional_usdt: float, book_depth_usdt: float | None) -> float:
    """Estimate slippage in bps based on order notional and available depth.

    If depth is unknown, returns a conservative default (8 bps).
    Otherwise, slippage increases as notional approaches 10% of top-10 depth.
    """
    if not book_depth_usdt or book_depth_usdt <= 0:
        return 8.0

    # Simple linear model: 0.5 bps + (notional / depth) * 100
    # E.g. 50 USDT on 5000 USDT depth -> 0.5 + (50/5000)*100 = 1.5 bps
    slippage = 0.5 + (notional_usdt / book_depth_usdt) * 100.0
    return max(1.0, min(100.0, slippage))

def get_exit_price(base_price: float, side: str, spread_bps: float, slippage_bps: float, notional_usdt: float = 0.0, book_depth_usdt: float | None = None) -> float:
    """Apply spread and slippage to get simulation exit price."""
    dynamic_slippage = calculate_dynamic_slippage_bps(notional_usdt, book_depth_usdt) if book_depth_usdt else slippage_bps
    penalty = (spread_bps + dynamic_slippage) / 10_000.0
    # To exit a LONG (selling), we get a lower price
    if side.upper() == "LONG":
        return base_price * (1.0 - penalty)
    # To exit a SHORT (buying back), we pay a higher price
    else:
        return base_price * (1.0 + penalty)

def get_entry_price(base_price: float, side: str, spread_bps: float, slippage_bps: float, notional_usdt: float = 0.0, book_depth_usdt: float | None = None) -> float:
    """Apply spread and slippage to get simulation entry price."""
    dynamic_slippage = calculate_dynamic_slippage_bps(notional_usdt, book_depth_usdt) if book_depth_usdt else slippage_bps
    penalty = (spread_bps + dynamic_slippage) / 10_000.0
    # To enter a LONG (buying), we pay a higher price
    if side.upper() == "LONG":
        return base_price * (1.0 + penalty)
    # To enter a SHORT (selling), we get a lower price
    else:
        return base_price * (1.0 - penalty)
