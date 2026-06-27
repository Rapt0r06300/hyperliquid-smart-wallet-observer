"""Deep paper execution model (S8 — V9, pm-backtest A2 / CloddsBot — SIM).

Models what filling a copy order would *really* cost, on real book state, so the
paper PnL reflects execution reality instead of an idealised mid-price fill:

  * taker path: pay the taker fee + half-spread + size/depth market impact;
  * maker path: earn the maker rebate, but face queue position and fill risk;
  * latency: optional time-decay cost while the order is in flight.

Everything is *simulated*. Nothing is sent to a real venue; there is no order id,
no signature, no endpoint. It only returns an effective fill price and a signed
cost in bps (positive = cost, negative = rebate credit). SAFETY: pure & paper.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class ExecModelConfig:
    taker_fee_bps: float = 4.5
    maker_rebate_bps: float = 1.0          # credited (negative cost) on a passive fill
    half_spread_bps: float = 1.0
    impact_coef_bps: float = 10.0          # impact when the order consumes the whole top depth
    latency_cost_bps_per_sec: float = 0.0
    # if depth is unknown we cannot trust the fill -> charge a conservative impact
    unknown_depth_impact_bps: float = 25.0


@dataclass(frozen=True, slots=True)
class ExecResult:
    fill_price: float
    slippage_bps: float
    fee_bps: float           # signed: + = fee paid, - = rebate earned
    latency_bps: float
    net_cost_bps: float      # total signed cost vs mid (slippage + fee + latency)
    queue_ratio: float | None
    is_maker: bool
    notional_usdc: float


def estimate_slippage_bps(
    notional_usdc: float,
    top_depth_usdc: float | None,
    *,
    config: ExecModelConfig | None = None,
) -> float:
    """Half-spread + size/depth market impact, in bps. Depth None -> conservative."""
    cfg = config or ExecModelConfig()
    if top_depth_usdc is None or top_depth_usdc <= 0:
        return cfg.half_spread_bps + cfg.unknown_depth_impact_bps
    consume_ratio = max(0.0, notional_usdc) / top_depth_usdc
    return cfg.half_spread_bps + cfg.impact_coef_bps * consume_ratio


def _apply_price(mid_price: float, side: str, signed_bps: float) -> float:
    # a positive cost moves the fill against you (buy higher, sell lower)
    adj = signed_bps / 10_000.0
    if side.upper() in {"LONG", "BUY"}:
        return mid_price * (1.0 + adj)
    return mid_price * (1.0 - adj)


def simulate_execution(
    *,
    side: str,
    notional_usdc: float,
    mid_price: float,
    top_depth_usdc: float | None = None,
    is_maker: bool = False,
    latency_sec: float = 0.0,
    queue_ahead_usdc: float = 0.0,
    config: ExecModelConfig | None = None,
) -> ExecResult:
    """Simulate filling ``notional_usdc`` at ``mid_price`` on the given book."""
    cfg = config or ExecModelConfig()
    latency_bps = max(0.0, latency_sec) * cfg.latency_cost_bps_per_sec

    if is_maker:
        # Passive fill: no spread paid, earn the rebate; model queue position.
        depth = top_depth_usdc if (top_depth_usdc and top_depth_usdc > 0) else None
        queue_ratio = None
        if depth is not None:
            queue_ratio = max(0.0, queue_ahead_usdc) / depth
        slippage_bps = 0.0
        fee_bps = -cfg.maker_rebate_bps
        net_cost_bps = slippage_bps + fee_bps + latency_bps
        fill_price = _apply_price(mid_price, side, net_cost_bps)
        return ExecResult(
            fill_price=round(fill_price, 10),
            slippage_bps=slippage_bps,
            fee_bps=fee_bps,
            latency_bps=latency_bps,
            net_cost_bps=net_cost_bps,
            queue_ratio=queue_ratio,
            is_maker=True,
            notional_usdc=notional_usdc,
        )

    # Taker path: pay fee + half-spread + impact.
    slippage_bps = estimate_slippage_bps(notional_usdc, top_depth_usdc, config=cfg)
    fee_bps = cfg.taker_fee_bps
    net_cost_bps = slippage_bps + fee_bps + latency_bps
    fill_price = _apply_price(mid_price, side, net_cost_bps)
    return ExecResult(
        fill_price=round(fill_price, 10),
        slippage_bps=slippage_bps,
        fee_bps=fee_bps,
        latency_bps=latency_bps,
        net_cost_bps=net_cost_bps,
        queue_ratio=None,
        is_maker=False,
        notional_usdc=notional_usdc,
    )


def round_trip_cost_bps(
    *,
    entry: ExecResult,
    exit_: ExecResult,
) -> float:
    """Total signed cost of a round trip (entry + exit), in bps."""
    return entry.net_cost_bps + exit_.net_cost_bps


__all__ = [
    "ExecModelConfig",
    "ExecResult",
    "estimate_slippage_bps",
    "simulate_execution",
    "round_trip_cost_bps",
]
