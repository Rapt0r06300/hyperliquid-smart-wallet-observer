"""V15 #198 — Hyperliquid-style maker/taker fee tiers by 14-day volume (for exact costs).

The default tier table is APPROXIMATE and fully overridable — the value is the *model*
(fees fall as 14d volume rises), used to compute exact entry+exit cost in the edge calc.
No fee number is asserted as live truth; pass your own tiers to be precise. Pure.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Sequence


@dataclass(frozen=True, slots=True)
class FeeTier:
    min_volume_14d_usd: float
    taker_bps: float
    maker_bps: float


# Approximate, descending tiers (override with live values for precision).
DEFAULT_FEE_TIERS: tuple[FeeTier, ...] = (
    FeeTier(0.0,            4.5, 1.5),
    FeeTier(5_000_000.0,    4.0, 1.2),
    FeeTier(25_000_000.0,   3.5, 1.0),
    FeeTier(100_000_000.0,  3.0, 0.8),
    FeeTier(500_000_000.0,  2.5, 0.5),
)


@dataclass(frozen=True, slots=True)
class FeeQuote:
    tier_index: int
    taker_bps: float
    maker_bps: float


def fee_for_volume(volume_14d_usd: float, *, tiers: Sequence[FeeTier] = DEFAULT_FEE_TIERS) -> FeeQuote:
    ordered = sorted(tiers, key=lambda t: t.min_volume_14d_usd)
    chosen = 0
    for i, t in enumerate(ordered):
        if float(volume_14d_usd) >= t.min_volume_14d_usd:
            chosen = i
    t = ordered[chosen]
    return FeeQuote(chosen, t.taker_bps, t.maker_bps)


def round_trip_cost_bps(
    *,
    volume_14d_usd: float,
    entry_is_maker: bool,
    exit_is_maker: bool,
    tiers: Sequence[FeeTier] = DEFAULT_FEE_TIERS,
) -> float:
    q = fee_for_volume(volume_14d_usd, tiers=tiers)
    entry = q.maker_bps if entry_is_maker else q.taker_bps
    exit_ = q.maker_bps if exit_is_maker else q.taker_bps
    return round(entry + exit_, 6)


__all__ = ["FeeTier", "DEFAULT_FEE_TIERS", "FeeQuote", "fee_for_volume", "round_trip_cost_bps"]
