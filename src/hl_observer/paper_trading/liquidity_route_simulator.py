"""Simulate local paper liquidity routes across book levels."""

from __future__ import annotations

from dataclasses import asdict, dataclass

from hl_observer.paper_trading.exec_model import DepthExecutionResult, simulate_depth_execution


@dataclass(frozen=True, slots=True)
class LiquidityRoute:
    side: str
    requested_notional_usdt: float
    mid_price: float
    execution: DepthExecutionResult
    paper_only: bool = True

    def as_dict(self) -> dict[str, object]:
        return {
            "side": self.side,
            "requested_notional_usdt": self.requested_notional_usdt,
            "mid_price": self.mid_price,
            "execution": asdict(self.execution),
            "paper_only": True,
            "external_action": False,
        }


def simulate_liquidity_route(
    *,
    side: str,
    notional_usdt: float,
    mid_price: float,
    asks: tuple[tuple[float, float], ...] = (),
    bids: tuple[tuple[float, float], ...] = (),
    min_fill_ratio: float = 0.90,
) -> LiquidityRoute:
    result = simulate_depth_execution(
        side=side,
        notional_usdc=notional_usdt,
        mid_price=mid_price,
        asks=asks,
        bids=bids,
        min_fill_ratio=min_fill_ratio,
    )
    return LiquidityRoute(
        side=str(side).upper(),
        requested_notional_usdt=round(float(notional_usdt or 0.0), 8),
        mid_price=round(float(mid_price or 0.0), 10),
        execution=result,
    )


__all__ = ["LiquidityRoute", "simulate_liquidity_route"]
