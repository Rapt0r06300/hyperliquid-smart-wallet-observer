"""Proportional paper sizing for wallet mirroring."""

from __future__ import annotations

from dataclasses import dataclass

from hl_observer.copy_wallet.wallet_tier import WalletTier


@dataclass(frozen=True, slots=True)
class ProportionalSizingConfig:
    follower_equity_usdt: float = 1000.0
    leader_equity_usdt: float = 100_000.0
    base_copy_ratio: float = 0.05
    min_margin_usdt: float = 5.0
    max_margin_usdt: float = 75.0
    max_equity_fraction: float = 0.075


@dataclass(frozen=True, slots=True)
class ProportionalSizingDecision:
    accepted: bool
    margin_usdt: float
    leader_notional_usdt: float
    ratio_used: float
    cap_usdt: float
    reason: str


def size_proportional_to_leader(
    *,
    leader_notional_usdt: float,
    tier: WalletTier,
    config: ProportionalSizingConfig | None = None,
) -> ProportionalSizingDecision:
    cfg = config or ProportionalSizingConfig()
    if tier.copy_ratio_multiplier <= 0:
        return ProportionalSizingDecision(False, 0.0, float(leader_notional_usdt or 0.0), 0.0, 0.0, "WALLET_TIER_REJECTED")
    if leader_notional_usdt <= 0:
        return ProportionalSizingDecision(False, 0.0, float(leader_notional_usdt or 0.0), 0.0, 0.0, "LEADER_NOTIONAL_INVALID")
    equity_ratio = max(0.0, float(cfg.follower_equity_usdt or 0.0) / max(1.0, float(cfg.leader_equity_usdt or 1.0)))
    ratio = max(0.0, float(cfg.base_copy_ratio) * tier.copy_ratio_multiplier * equity_ratio)
    raw_margin = float(leader_notional_usdt) * ratio
    cap = min(float(cfg.max_margin_usdt), float(tier.max_margin_usdt), float(cfg.follower_equity_usdt) * float(cfg.max_equity_fraction))
    margin = min(max(0.0, raw_margin), max(0.0, cap))
    if margin < float(cfg.min_margin_usdt):
        return ProportionalSizingDecision(False, round(margin, 8), float(leader_notional_usdt), round(ratio, 10), round(cap, 8), "SIZED_BELOW_MIN_MARGIN")
    return ProportionalSizingDecision(True, round(margin, 8), float(leader_notional_usdt), round(ratio, 10), round(cap, 8), "OK")


__all__ = ["ProportionalSizingConfig", "ProportionalSizingDecision", "size_proportional_to_leader"]
