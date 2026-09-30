from hl_observer.hyperliquid.schemas import SignalDecision, WalletProfile
from hl_observer.wallets.scoring import score_wallet


def test_wallet_scoring_penalizes_small_sample():
    score = score_wallet(WalletProfile(address="0xabc", trades_count=3))

    assert score.decision == SignalDecision.REJECT_SAMPLE_TOO_SMALL
    assert "sample_size_too_small" in score.reasons
