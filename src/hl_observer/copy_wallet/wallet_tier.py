"""Wallet tiering for copy-wallet paper simulation."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class WalletTier:
    name: str
    min_score: float
    copy_ratio_multiplier: float
    max_margin_usdt: float
    slippage_budget_bps: float


TIERS: tuple[WalletTier, ...] = (
    WalletTier("S", 0.90, 1.35, 75.0, 16.0),
    WalletTier("A", 0.78, 1.10, 55.0, 18.0),
    WalletTier("B", 0.65, 0.85, 35.0, 22.0),
    WalletTier("C", 0.55, 0.55, 20.0, 28.0),
)
REJECTED_TIER = WalletTier("REJECTED", 1.01, 0.0, 0.0, 0.0)


def tier_for_wallet_score(wallet_score: float, copyability_score: float) -> WalletTier:
    effective = min(float(wallet_score or 0.0), float(copyability_score or 0.0))
    for tier in TIERS:
        if effective >= tier.min_score:
            return tier
    return REJECTED_TIER


__all__ = ["REJECTED_TIER", "TIERS", "WalletTier", "tier_for_wallet_score"]
