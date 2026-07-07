"""Slippage/depth guard for wallet-mirror paper entries."""

from __future__ import annotations

from dataclasses import dataclass

from hl_observer.signals.depth_guard import depth_fill_guard


@dataclass(frozen=True, slots=True)
class SlippageGuardConfig:
    max_slippage_bps: float = 18.0
    min_fill_ratio: float = 0.90


@dataclass(frozen=True, slots=True)
class SlippageGuardDecision:
    accepted: bool
    reason: str
    average_fill_price: float | None
    fill_ratio: float
    slippage_bps: float
    evidence: dict[str, object]


def evaluate_slippage_guard_v2(
    *,
    side: str,
    notional_usdt: float,
    mid_price: float,
    asks: tuple[tuple[float, float], ...] = (),
    bids: tuple[tuple[float, float], ...] = (),
    config: SlippageGuardConfig | None = None,
) -> SlippageGuardDecision:
    cfg = config or SlippageGuardConfig()
    ok, reason, result = depth_fill_guard(
        side=side,
        needed_usd=notional_usdt,
        mid_price=mid_price,
        asks=asks,
        bids=bids,
        min_fill_ratio=cfg.min_fill_ratio,
        max_slippage_bps=cfg.max_slippage_bps,
    )
    return SlippageGuardDecision(
        accepted=ok,
        reason=reason or "SLIPPAGE_GUARD_OK",
        average_fill_price=result.average_fill_price,
        fill_ratio=result.fill_ratio,
        slippage_bps=result.slippage_bps,
        evidence={
            "requested_notional_usdt": round(float(notional_usdt or 0.0), 8),
            "mid_price": round(float(mid_price or 0.0), 10),
            "max_slippage_bps": cfg.max_slippage_bps,
            "min_fill_ratio": cfg.min_fill_ratio,
            "depth_result": {
                "requested_notional_usdc": result.requested_notional_usdc,
                "filled_notional_usdc": result.filled_notional_usdc,
                "missed_notional_usdc": result.missed_notional_usdc,
                "average_fill_price": result.average_fill_price,
                "fill_ratio": result.fill_ratio,
                "partial": result.partial,
                "missed": result.missed,
                "slippage_bps": result.slippage_bps,
                "levels_consumed": result.levels_consumed,
                "reason": result.reason,
            },
        },
    )


__all__ = ["SlippageGuardConfig", "SlippageGuardDecision", "evaluate_slippage_guard_v2"]

