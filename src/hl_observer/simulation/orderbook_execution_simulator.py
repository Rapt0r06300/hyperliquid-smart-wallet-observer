from __future__ import annotations

import math
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
    economic_fill_price: float | None
    market_impact_bps: float | None
    adverse_selection_bps: float | None
    latency_cost_bps: float | None
    all_in_cost_usdc: float | None
    book_age_ms: int | None
    replay_safe: bool
    unmeasured_costs: tuple[str, ...]


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
    book_age_ms: int | None = None,
    max_book_age_ms: int | None = None,
    latency_cost_bps: float | None = None,
    adverse_selection_bps: float | None = None,
    residual_impact_bps: float | None = None,
) -> OrderbookExecutionResult:
    measured_costs = {
        "latency_cost_bps": latency_cost_bps,
        "adverse_selection_bps": adverse_selection_bps,
        "residual_impact_bps": residual_impact_bps,
    }
    unmeasured = tuple(
        key
        for key, value in measured_costs.items()
        if value is None
        or not math.isfinite(float(value))
        or float(value) < 0.0
    )
    age_measured = book_age_ms is not None and max_book_age_ms is not None
    stale = bool(
        age_measured
        and (int(book_age_ms) < 0 or int(book_age_ms) > int(max_book_age_ms))
    )
    if stale:
        return OrderbookExecutionResult(
            side=str(side).upper(),
            requested_notional_usdc=round(float(notional_usdc), 10),
            filled_notional_usdc=0.0,
            missed_notional_usdc=round(float(notional_usdc), 10),
            average_fill_price=None,
            fee_usdc=0.0,
            slippage_bps=0.0,
            fill_ratio=0.0,
            partial=False,
            missed=True,
            latency_ms=max(0, int(latency_ms)),
            reason="STALE_BOOK",
            economic_fill_price=None,
            market_impact_bps=(float(residual_impact_bps) if residual_impact_bps is not None else None),
            adverse_selection_bps=(float(adverse_selection_bps) if adverse_selection_bps is not None else None),
            latency_cost_bps=(float(latency_cost_bps) if latency_cost_bps is not None else None),
            all_in_cost_usdc=None,
            book_age_ms=int(book_age_ms),
            replay_safe=False,
            unmeasured_costs=unmeasured,
        )
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
    additional_bps = (
        sum(float(value) for value in measured_costs.values())
        if not unmeasured
        else None
    )
    economic_fill_price = None
    all_in_cost = None
    if estimate.average_price is not None and additional_bps is not None:
        direction = 1.0 if str(side).upper() == "BUY" else -1.0
        economic_fill_price = round(
            estimate.average_price * (1.0 + direction * additional_bps / 10_000.0),
            10,
        )
        all_in_cost = round(
            fee + estimate.filled_notional_usdc * additional_bps / 10_000.0,
            10,
        )
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
        economic_fill_price=economic_fill_price,
        market_impact_bps=(float(residual_impact_bps) if residual_impact_bps is not None else None),
        adverse_selection_bps=(float(adverse_selection_bps) if adverse_selection_bps is not None else None),
        latency_cost_bps=(float(latency_cost_bps) if latency_cost_bps is not None else None),
        all_in_cost_usdc=all_in_cost,
        book_age_ms=int(book_age_ms) if book_age_ms is not None else None,
        replay_safe=bool(age_measured and not stale and not unmeasured),
        unmeasured_costs=unmeasured,
    )


__all__ = ["OrderbookExecutionResult", "simulate_orderbook_execution"]
