from __future__ import annotations

from hl_observer.hyperliquid.schemas import SignalDecision, WalletProfile, WalletScore, WalletStyle
from hl_observer.utils.math import clamp


def score_wallet(profile: WalletProfile) -> WalletScore:
    """Multi-metric wallet scoring aligned with research best practices.

    Key design decisions (per AGENTS.md §A6.7 and research findings):
    - Win rate is the primary quality filter (75% of active HL wallets lose money).
    - Profit factor > 1.0 is required for a positive expected value.
    - Low sample count triggers OBSERVE_ONLY, never rejection (still learning).
    - Martingale / one_big_win patterns hard-cap the score (per AGENTS.md §A6.7).
    - Drawdown is penalised heavily: high MDD = fragile alpha.
    """
    reasons: list[str] = []
    flags: list[str] = []

    # === Component scores (max total = 100) ===
    # Win rate: primary quality signal — research confirms this is the #1 predictor
    win_score = clamp(profile.win_rate * 30.0, 0.0, 30.0)

    # Profit factor: must be > 1.0 to have positive expectancy
    pf_score = clamp((profile.profit_factor - 1.0) * 20.0, 0.0, 20.0)

    # PnL consistency (30d rolling proxy)
    pnl_score = clamp(profile.pnl_bps / 800.0 * 15.0, 0.0, 15.0)

    # Sample confidence (need ≥ 30 trades; penalise low count)
    sample_score = clamp(profile.trades_count / 50.0 * 15.0, 0.0, 15.0)

    # Activity (active days shows ongoing edge, not one-off)
    activity_score = clamp(profile.active_days / 14.0 * 10.0, 0.0, 10.0)

    # Sharpe-like bonus: high PnL with low drawdown = quality alpha
    sharpe_proxy = (profile.pnl_bps / max(1.0, profile.max_drawdown_bps)) if profile.pnl_bps > 0 else 0.0
    sharpe_bonus = clamp(sharpe_proxy * 5.0, 0.0, 10.0)

    # === Penalties ===
    drawdown_penalty = clamp(profile.max_drawdown_bps / 300.0 * 15.0, 0.0, 15.0)
    concentration_penalty = clamp(profile.top_trade_pnl_share * 20.0, 0.0, 20.0)
    toxicity_penalty = clamp(profile.toxicity_score * 20.0, 0.0, 20.0)

    raw_score = (
        win_score
        + pf_score
        + pnl_score
        + sample_score
        + activity_score
        + sharpe_bonus
        - drawdown_penalty
        - concentration_penalty
        - toxicity_penalty
    )

    # === Hard score caps for dangerous wallet patterns (AGENTS.md §A6.7) ===
    if profile.style == WalletStyle.MARTINGALE_RISK:
        flags.append("FLAG_MARTINGALE_LIKE")
        raw_score = min(raw_score, 60.0)
        reasons.append("martingale_pattern_detected")

    if profile.style == WalletStyle.ONE_BIG_WIN or profile.top_trade_pnl_share > 0.5:
        flags.append("FLAG_SINGLE_BIG_WIN")
        raw_score = min(raw_score, 65.0)
        reasons.append("one_big_win_risk")

    if profile.trades_count < 20:
        flags.append("FLAG_LOW_SAMPLE_SIZE")
        raw_score = min(raw_score, 55.0)
        reasons.append("sample_size_too_small")

    if profile.toxicity_score > 0.6:
        reasons.append("wallet_toxicity_high")

    score = clamp(raw_score, 0.0, 100.0)

    # === Decision ===
    if "sample_size_too_small" in reasons and profile.trades_count < 10:
        decision = SignalDecision.REJECT_SAMPLE_TOO_SMALL
    elif "wallet_toxicity_high" in reasons:
        decision = SignalDecision.REJECT_WALLET_TOXIC
    elif "martingale_pattern_detected" in reasons:
        decision = SignalDecision.REJECT_MARTINGALE_PATTERN
    elif "one_big_win_risk" in reasons:
        decision = SignalDecision.REJECT_ONE_BIG_WIN_WALLET
    elif score >= 72 and not reasons:
        decision = SignalDecision.PAPER_CANDIDATE
    elif score >= 55:
        decision = SignalDecision.OBSERVE_ONLY
    else:
        decision = SignalDecision.OBSERVE_ONLY

    return WalletScore(
        address=profile.address,
        score=score,
        decision=decision,
        reasons=reasons,
        metrics={
            "win_score": win_score,
            "profit_factor_score": pf_score,
            "pnl_score": pnl_score,
            "sample_score": sample_score,
            "activity_score": activity_score,
            "sharpe_bonus": sharpe_bonus,
            "drawdown_penalty": drawdown_penalty,
            "concentration_penalty": concentration_penalty,
            "toxicity_penalty": toxicity_penalty,
            "flags": len(flags),
        },
    )
