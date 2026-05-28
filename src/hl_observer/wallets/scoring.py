from __future__ import annotations

from hl_observer.hyperliquid.schemas import SignalDecision, WalletProfile, WalletScore, WalletStatus
from hl_observer.utils.math import clamp


def score_wallet(profile: WalletProfile) -> WalletScore:
    reasons: list[str] = []

    # 1. Mandatory thresholds
    if profile.history_days < 7:
        reasons.append("insufficient_history")
    if profile.closed_pnl_count < 10:
        reasons.append("insufficient_trades")
    if profile.top_trade_pnl_share > 0.35:
        reasons.append("pnl_concentration_too_high")
    if profile.copyability_score < 40:
        reasons.append("low_copyability")
    # Illiquid coins penalty
    if profile.copyability_score < 30:
        reasons.append("trades_illiquid_assets")
    if profile.toxicity_score > 0.7:
        reasons.append("wallet_toxicity_high")

    # 2. Weighted scoring
    # Sample size (trades) - max 20 pts
    sample_score = clamp(profile.closed_pnl_count / 50.0 * 20.0, 0.0, 20.0)

    # History days - max 15 pts
    history_score = clamp(profile.history_days / 30.0 * 15.0, 0.0, 15.0)

    # Winrate - max 15 pts
    win_score = clamp(profile.win_rate * 15.0, 0.0, 15.0)

    # Profit factor - max 15 pts
    pf_score = clamp((profile.profit_factor - 1.0) * 15.0, 0.0, 15.0)

    # Regularity & Recent activity - max 20 pts
    reg_score = clamp(profile.regularity_score / 100.0 * 10.0 + profile.recent_activity_score / 100.0 * 10.0, 0.0, 20.0)

    # Copyability - max 15 pts
    copy_score = clamp(profile.copyability_score / 100.0 * 15.0, 0.0, 15.0)

    # Penalties
    drawdown_penalty = clamp(profile.max_drawdown_pct / 20.0 * 15.0, 0.0, 15.0)
    concentration_penalty = clamp(profile.top_trade_pnl_share * 20.0, 0.0, 20.0)
    toxicity_penalty = clamp(profile.toxicity_score * 20.0, 0.0, 20.0)

    score = clamp(
        sample_score
        + history_score
        + win_score
        + pf_score
        + reg_score
        + copy_score
        - drawdown_penalty
        - concentration_penalty
        - toxicity_penalty,
        0.0,
        100.0,
    )

    # 3. Status Assignment
    if "insufficient_history" in reasons or "insufficient_trades" in reasons:
        status = WalletStatus.INSUFFICIENT_DATA
        decision = SignalDecision.OBSERVE_ONLY
    elif "wallet_toxicity_high" in reasons:
        status = WalletStatus.REJECTED
        decision = SignalDecision.REJECT_WALLET_TOXIC
    elif "pnl_concentration_too_high" in reasons:
        status = WalletStatus.WATCH_ONLY
        decision = SignalDecision.REJECT_ONE_BIG_WIN_WALLET
    elif score >= 80:
        status = WalletStatus.ACTIVE_LEADER
        decision = SignalDecision.TESTNET_CANDIDATE
    elif score >= 65:
        status = WalletStatus.SHORTLISTED
        decision = SignalDecision.PAPER_CANDIDATE
    else:
        status = WalletStatus.WATCH_ONLY
        decision = SignalDecision.OBSERVE_ONLY

    return WalletScore(
        address=profile.address,
        score=score,
        status=status,
        decision=decision,
        reasons=reasons,
        metrics={
            "sample_score": sample_score,
            "history_score": history_score,
            "win_score": win_score,
            "profit_factor_score": pf_score,
            "regularity_score": reg_score,
            "copy_score": copy_score,
            "drawdown_penalty": drawdown_penalty,
            "concentration_penalty": concentration_penalty,
            "toxicity_penalty": toxicity_penalty,
        },
    )
