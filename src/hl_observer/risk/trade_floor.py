"""Trade floor + fee/gas accounting (S7 — V9, MrFadiAi A4).

Two protections:
  1. Minimum trade size ($1.50) — tiny tickets are noise and never clear costs.
  2. Cost-aware profit threshold — the required edge is raised so expected
     profit covers round-trip fees and any fixed gas/cost.

SAFETY: pure. Output gates a *paper* intent only.
"""

from __future__ import annotations

from dataclasses import dataclass, field

MIN_TRADE_USDC = 1.50


@dataclass(frozen=True, slots=True)
class TradeFloorConfig:
    min_trade_usdc: float = MIN_TRADE_USDC
    taker_fee_bps: float = 4.5
    round_trips: int = 2
    fixed_cost_usdc: float = 0.0


@dataclass(frozen=True, slots=True)
class TradeFloorDecision:
    passes_floor: bool
    required_edge_bps: float
    reasons: tuple[str, ...] = field(default_factory=tuple)


def meets_floor(notional_usdc: float, *, min_trade_usdc: float = MIN_TRADE_USDC) -> bool:
    return notional_usdc >= min_trade_usdc


def required_edge_bps(notional_usdc: float, config: TradeFloorConfig | None = None) -> float:
    """Edge (bps) needed just to break even after fees + fixed cost."""
    cfg = config or TradeFloorConfig()
    fee_bps = cfg.taker_fee_bps * max(1, cfg.round_trips)
    fixed_bps = 0.0
    if notional_usdc > 0 and cfg.fixed_cost_usdc > 0:
        fixed_bps = cfg.fixed_cost_usdc / notional_usdc * 10_000.0
    return fee_bps + fixed_bps


def evaluate_trade_floor(
    notional_usdc: float,
    config: TradeFloorConfig | None = None,
) -> TradeFloorDecision:
    cfg = config or TradeFloorConfig()
    reasons: list[str] = []
    passes = meets_floor(notional_usdc, min_trade_usdc=cfg.min_trade_usdc)
    if not passes:
        reasons.append(f"NOTIONAL_BELOW_FLOOR_{notional_usdc:.2f}<{cfg.min_trade_usdc:.2f}")
    req = required_edge_bps(notional_usdc, cfg)
    reasons.append(f"required_edge_bps={req:.2f}")
    return TradeFloorDecision(passes_floor=passes, required_edge_bps=req, reasons=tuple(reasons))
