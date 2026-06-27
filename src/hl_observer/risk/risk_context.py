from __future__ import annotations

from pydantic import BaseModel


class AdaptiveRiskContext(BaseModel):
    signal_age_ms: int = 0
    price_moved_bps: float = 0.0
    spread_bps: float = 0.0
    estimated_slippage_bps: float = 0.0
    depth_usdc: float = 0.0
    wallet_score: float = 0.0
    wallet_coin_score: float = 0.0
    opening_pattern_score: float = 0.0
    pattern_sample_size: int = 0
    coin: str = "BTC"
    volatility_regime: str = "normal"
    wallet_action: str = "OPEN"
