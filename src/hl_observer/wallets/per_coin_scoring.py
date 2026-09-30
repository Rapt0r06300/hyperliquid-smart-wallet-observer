from __future__ import annotations

from pydantic import BaseModel, Field

from hl_observer.wallets.wallet_coin_profile import WalletCoinProfile


class WalletCoinScore(BaseModel):
    wallet_address: str
    coin: str
    performance_score: float = 0.0
    risk_score: float = 0.0
    consistency_score: float = 0.0
    copyability_score: float = 0.0
    liquidity_score: float = 0.0
    timing_score: float = 0.0
    toxicity_penalty: float = 0.0
    final_score: float = 0.0
    decision: str = "OBSERVE_ONLY"
    reasons: list[str] = Field(default_factory=list)


def score_wallet_coin(profile: WalletCoinProfile) -> WalletCoinScore:
    pnl = profile.estimated_pnl_usdc
    roi = profile.estimated_roi_pct
    performance_score = 50.0
    reasons: list[str] = []
    if pnl is not None:
        performance_score += max(-35.0, min(35.0, pnl / 1000.0 * 35.0))
        reasons.append("pnl_available")
    else:
        reasons.append("pnl_incomplete")
    if roi is not None:
        performance_score += max(-15.0, min(15.0, roi))
        reasons.append("roi_available")
    else:
        reasons.append("roi_incomplete")
    consistency_score = (profile.win_rate or 0.0) * 100.0 if profile.win_rate is not None else 35.0
    timing_score = 65.0 if profile.last_activity_ms else 25.0
    risk_score = max(0.0, 100.0 - profile.toxicity_score)
    final_score = (
        performance_score * 0.30
        + risk_score * 0.15
        + consistency_score * 0.15
        + profile.copyability_score * 0.20
        + profile.liquidity_score * 0.15
        + timing_score * 0.05
        - profile.toxicity_score * 0.20
    )
    final_score = max(0.0, min(100.0, final_score))
    decision = "WATCHLIST" if final_score >= 70 and profile.status == "SCORABLE" else "OBSERVE_ONLY"
    if profile.fills_count < 3:
        reasons.append("not_enough_coin_fills")
    if profile.liquidity_score < 50:
        reasons.append("liquidity_unproven")
    return WalletCoinScore(
        wallet_address=profile.wallet_address,
        coin=profile.coin,
        performance_score=max(0.0, min(100.0, performance_score)),
        risk_score=risk_score,
        consistency_score=consistency_score,
        copyability_score=profile.copyability_score,
        liquidity_score=profile.liquidity_score,
        timing_score=timing_score,
        toxicity_penalty=profile.toxicity_score,
        final_score=final_score,
        decision=decision,
        reasons=reasons,
    )

