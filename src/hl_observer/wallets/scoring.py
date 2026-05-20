from __future__ import annotations

from hl_observer.hyperliquid.schemas import SignalDecision, WalletProfile, WalletScore
from hl_observer.utils.math import clamp


def score_wallet(profile: WalletProfile) -> WalletScore:
    reasons: list[str] = []
    sample_score = clamp(profile.trades_count / 75.0 * 25.0, 0.0, 25.0)
    activity_score = clamp(profile.active_days / 14.0 * 15.0, 0.0, 15.0)
    win_score = clamp(profile.win_rate * 20.0, 0.0, 20.0)
    pf_score = clamp((profile.profit_factor - 1.0) * 15.0, 0.0, 15.0)
    pnl_score = clamp(profile.pnl_bps / 1000.0 * 15.0, 0.0, 15.0)
    drawdown_penalty = clamp(profile.max_drawdown_bps / 500.0 * 10.0, 0.0, 10.0)
    concentration_penalty = clamp(profile.top_trade_pnl_share * 15.0, 0.0, 15.0)
    toxicity_penalty = clamp(profile.toxicity_score * 20.0, 0.0, 20.0)
    score = clamp(
        sample_score
        + activity_score
        + win_score
        + pf_score
        + pnl_score
        - drawdown_penalty
        - concentration_penalty
        - toxicity_penalty,
        0.0,
        100.0,
    )

    if profile.trades_count < 30:
        reasons.append("sample_size_too_small")
    if profile.top_trade_pnl_share > 0.4:
        reasons.append("one_big_win_risk")
    if profile.toxicity_score > 0.6:
        reasons.append("wallet_toxicity_high")

    decision = SignalDecision.PAPER_CANDIDATE if score >= 75 and not reasons else SignalDecision.OBSERVE_ONLY
    if "sample_size_too_small" in reasons:
        decision = SignalDecision.REJECT_SAMPLE_TOO_SMALL
    if "one_big_win_risk" in reasons:
        decision = SignalDecision.REJECT_ONE_BIG_WIN_WALLET
    if "wallet_toxicity_high" in reasons:
        decision = SignalDecision.REJECT_WALLET_TOXIC

    return WalletScore(
        address=profile.address,
        score=score,
        decision=decision,
        reasons=reasons,
        metrics={
            "sample_score": sample_score,
            "activity_score": activity_score,
            "win_score": win_score,
            "profit_factor_score": pf_score,
            "pnl_score": pnl_score,
        },
    )
