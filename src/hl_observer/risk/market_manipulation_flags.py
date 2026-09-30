"""Paper-only market quality flags before accepting copy signals."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True, slots=True)
class MarketManipulationFlags:
    suspicious: bool
    flags: tuple[str, ...] = field(default_factory=tuple)
    risk_score: float = 0.0


def detect_market_manipulation_flags(
    *,
    spread_bps: float,
    volatility_bps: float,
    same_wallet_ratio: float = 0.0,
    cancel_rate: float = 0.0,
    max_spread_bps: float = 20.0,
    max_volatility_bps: float = 80.0,
    max_same_wallet_ratio: float = 0.65,
    max_cancel_rate: float = 0.75,
) -> MarketManipulationFlags:
    flags: list[str] = []
    if spread_bps > max_spread_bps:
        flags.append("SPREAD_MANIPULATION_RISK")
    if volatility_bps > max_volatility_bps:
        flags.append("VOLATILITY_SPIKE_RISK")
    if same_wallet_ratio > max_same_wallet_ratio:
        flags.append("WALLET_CLUSTER_CONCENTRATION_RISK")
    if cancel_rate > max_cancel_rate:
        flags.append("ORDERBOOK_CANCEL_RATE_RISK")
    score = min(1.0, 0.25 * len(flags))
    return MarketManipulationFlags(suspicious=bool(flags), flags=tuple(flags), risk_score=round(score, 8))


__all__ = ["MarketManipulationFlags", "detect_market_manipulation_flags"]
