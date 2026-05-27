from hl_observer.hyperliquid.schemas import SignalDecision, WalletProfile, WalletStatus
from hl_observer.wallets.scoring import score_wallet


def test_wallet_scoring_insufficient_data():
    profile = WalletProfile(address="0xabc", closed_pnl_count=3, history_days=2.0)
    score = score_wallet(profile)

    assert score.status == WalletStatus.INSUFFICIENT_DATA
    assert score.decision == SignalDecision.OBSERVE_ONLY
    assert "insufficient_history" in score.reasons
    assert "insufficient_trades" in score.reasons

def test_wallet_scoring_high_concentration():
    profile = WalletProfile(
        address="0xabc",
        closed_pnl_count=20,
        history_days=15.0,
        top_trade_pnl_share=0.5,
        copyability_score=50.0
    )
    score = score_wallet(profile)

    assert score.status == WalletStatus.WATCH_ONLY
    assert score.decision == SignalDecision.REJECT_ONE_BIG_WIN_WALLET
    assert "pnl_concentration_too_high" in score.reasons

def test_wallet_scoring_active_leader():
    profile = WalletProfile(
        address="0xabc",
        closed_pnl_count=100,
        history_days=60.0,
        win_rate=0.7,
        profit_factor=2.5,
        regularity_score=90.0,
        recent_activity_score=80.0,
        copyability_score=85.0,
        max_drawdown_pct=5.0,
        top_trade_pnl_share=0.1
    )
    score = score_wallet(profile)

    assert score.status == WalletStatus.ACTIVE_LEADER
    assert score.decision == SignalDecision.TESTNET_CANDIDATE
    assert score.score >= 80
