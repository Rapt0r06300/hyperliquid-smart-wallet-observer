from __future__ import annotations

from dataclasses import dataclass

from hl_observer.paper_trading.exec_model import simulate_depth_execution


@dataclass(frozen=True, slots=True)
class SlippageEstimate:
    average_price: float | None
    filled_notional_usdc: float
    missed_notional_usdc: float
    slippage_bps: float
    fill_ratio: float
    partial: bool
    missed: bool
    levels_consumed: int


def estimate_orderbook_slippage(
    *,
    side: str,
    notional_usdc: float,
    mid_price: float,
    asks: list[tuple[float, float]] | tuple[tuple[float, float], ...] = (),
    bids: list[tuple[float, float]] | tuple[tuple[float, float], ...] = (),
    min_fill_ratio: float = 0.85,
) -> SlippageEstimate:
    result = simulate_depth_execution(
        side=side,
        notional_usdc=notional_usdc,
        mid_price=mid_price,
        asks=asks,
        bids=bids,
        min_fill_ratio=min_fill_ratio,
    )
    return SlippageEstimate(
        average_price=result.average_fill_price,
        filled_notional_usdc=result.filled_notional_usdc,
        missed_notional_usdc=result.missed_notional_usdc,
        slippage_bps=result.slippage_bps,
        fill_ratio=result.fill_ratio,
        partial=result.partial,
        missed=result.missed,
        levels_consumed=result.levels_consumed,
    )


__all__ = ["SlippageEstimate", "estimate_orderbook_slippage"]
