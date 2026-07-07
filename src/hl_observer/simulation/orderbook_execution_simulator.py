from __future__ import annotations

from dataclasses import dataclass

from hl_observer.simulation.fee_model import compute_fee_usdc
from hl_observer.simulation.slippage_model import SlippageEstimate, estimate_orderbook_slippage


@dataclass(frozen=True, slots=True)
class OrderbookExecutionResult:
    side: str
    requested_notional_usdc: float
    filled_notional_usdc: float
    missed_notional_usdc: float
    average_fill_price: float | None
    fee_usdc: float
    slippage_bps: float
    fill_ratio: float
    partial: bool
    missed: bool
    latency_ms: int
    reason: str


def simulate_orderbook_execution(
    *,
    side: str,
    notional_usdc: float,
    mid_price: float,
    asks: list[tuple[float, float]] | tuple[tuple[float, float], ...] = (),
    bids: list[tuple[float, float]] | tuple[tuple[float, float], ...] = (),
    fee_bps: float = 4.5,
    latency_ms: int = 0,
    min_fill_ratio: float = 0.85,
) -> OrderbookExecutionResult:
    estimate: SlippageEstimate = estimate_orderbook_slippage(
        side=side,
        notional_usdc=notional_usdc,
        mid_price=mid_price,
        asks=asks,
        bids=bids,
        min_fill_ratio=min_fill_ratio,
    )
    reason = "FILLED"
    if estimate.missed:
        reason = "MISSED_FILL"
    elif estimate.partial:
        reason = "PARTIAL_FILL"
    fee = compute_fee_usdc(estimate.filled_notional_usdc, fee_bps)
    return OrderbookExecutionResult(
        side=str(side).upper(),
        requested_notional_usdc=round(float(notional_usdc), 10),
        filled_notional_usdc=estimate.filled_notional_usdc,
        missed_notional_usdc=estimate.missed_notional_usdc,
        average_fill_price=estimate.average_price,
        fee_usdc=fee,
        slippage_bps=estimate.slippage_bps,
        fill_ratio=estimate.fill_ratio,
        partial=estimate.partial,
        missed=estimate.missed,
        latency_ms=max(0, int(latency_ms)),
        reason=reason,
    )


__all__ = ["OrderbookExecutionResult", "simulate_orderbook_execution"]
