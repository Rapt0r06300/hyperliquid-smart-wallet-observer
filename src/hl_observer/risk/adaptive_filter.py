from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, Field

from hl_observer.config.settings import Settings
from hl_observer.risk.risk_context import AdaptiveRiskContext


class AdaptiveRiskLevel(StrEnum):
    BLOCK = "BLOCK"
    OBSERVE_ONLY = "OBSERVE_ONLY"
    TINY_PAPER = "TINY_PAPER"
    SMALL_PAPER = "SMALL_PAPER"
    NORMAL_PAPER = "NORMAL_PAPER"
    TESTNET_CANDIDATE_LOCKED = "TESTNET_CANDIDATE_LOCKED"


class AdaptiveRiskDecision(BaseModel):
    allowed: bool
    risk_level: AdaptiveRiskLevel
    reasons: list[str] = Field(default_factory=list)
    paper_size_usdc: float = 0.0


def apply_adaptive_risk_filter(context: AdaptiveRiskContext, settings: Settings) -> AdaptiveRiskDecision:
    cfg = settings.adaptive_risk_filter
    reasons: list[str] = []
    action = context.wallet_action.upper()
    if cfg.block_if_wallet_reducing and action == "REDUCE":
        return AdaptiveRiskDecision(allowed=False, risk_level=AdaptiveRiskLevel.BLOCK, reasons=["wallet_reducing"])
    if cfg.block_if_wallet_closing and action == "CLOSE":
        return AdaptiveRiskDecision(allowed=False, risk_level=AdaptiveRiskLevel.BLOCK, reasons=["wallet_closing"])
    if context.signal_age_ms > cfg.max_signal_age_ms:
        return AdaptiveRiskDecision(allowed=False, risk_level=AdaptiveRiskLevel.BLOCK, reasons=["signal_stale"])
    if context.spread_bps > cfg.max_spread_bps:
        return AdaptiveRiskDecision(allowed=False, risk_level=AdaptiveRiskLevel.BLOCK, reasons=["spread_too_wide"])
    if context.slippage_bps > cfg.max_estimated_slippage_bps:
        return AdaptiveRiskDecision(allowed=False, risk_level=AdaptiveRiskLevel.BLOCK, reasons=["slippage_too_high"])
    if context.depth_usdc < cfg.min_orderbook_depth_usdc:
        return AdaptiveRiskDecision(allowed=False, risk_level=AdaptiveRiskLevel.BLOCK, reasons=["liquidity_too_low"])
    if context.wallet_score < cfg.min_wallet_score or context.wallet_coin_score < cfg.min_wallet_coin_score:
        return AdaptiveRiskDecision(allowed=False, risk_level=AdaptiveRiskLevel.OBSERVE_ONLY, reasons=["wallet_score_low"])
    if context.opening_pattern_score < cfg.min_opening_pattern_score:
        return AdaptiveRiskDecision(allowed=False, risk_level=AdaptiveRiskLevel.OBSERVE_ONLY, reasons=["pattern_score_low"])
    if context.pattern_sample_size < cfg.min_pattern_sample_size:
        return AdaptiveRiskDecision(allowed=False, risk_level=AdaptiveRiskLevel.OBSERVE_ONLY, reasons=["sample_size_too_low"])
    size = cfg.paper_normal_size_usdc
    if cfg.reduce_size_if_altcoin and context.coin.upper() not in {"BTC", "ETH", "SOL", "HYPE"}:
        size = min(size, cfg.paper_tiny_size_usdc)
        reasons.append("altcoin_size_reduced")
    if cfg.reduce_size_if_high_volatility and context.volatility_regime.lower() == "high":
        size = min(size, cfg.paper_small_size_usdc)
        reasons.append("high_volatility_size_reduced")
    return AdaptiveRiskDecision(
        allowed=True,
        risk_level=AdaptiveRiskLevel.TINY_PAPER if size <= cfg.paper_tiny_size_usdc else AdaptiveRiskLevel.NORMAL_PAPER,
        reasons=reasons or ["adaptive_risk_passed"],
        paper_size_usdc=min(size, cfg.paper_max_size_usdc),
    )
