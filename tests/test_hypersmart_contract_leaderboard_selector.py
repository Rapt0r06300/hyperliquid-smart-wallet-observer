import pytest
from hyper_smart_observer.copy_mode.leaderboard_selector import (
    select_leaderboard_shortlist,
    LeaderboardSelectionConfig,
    LeaderCandidateInput
)
from hyper_smart_observer.copy_mode.copy_models import LeaderStatus, LeaderRejectReason

@pytest.mark.contract
def test_contract_leaderboard_selector_truncated_address():
    """
    Contract: Truncated addresses (with ...) must be rejected.
    """
    candidate = LeaderCandidateInput(wallet_address="0x123...abc", history_days=10, closed_pnl_points=20)
    report = select_leaderboard_shortlist([candidate])
    entry = report.entries[0]
    assert entry.status == LeaderStatus.REJECTED
    assert LeaderRejectReason.TRUNCATED_ADDRESS_REJECTED.value in entry.refusal_reasons

@pytest.mark.contract
def test_contract_leaderboard_selector_pnl_concentration():
    """
    Contract: High PnL concentration must be rejected.
    """
    # 900 / 1000 = 0.9 concentration (> 0.65 default)
    candidate = LeaderCandidateInput(
        wallet_address="0x1111111111111111111111111111111111111111",
        history_days=10,
        closed_pnl_points=20,
        max_single_trade_pnl=900.0,
        total_closed_pnl=1000.0,
        consistency_score=100.0,
        sample_confidence=100.0
    )
    report = select_leaderboard_shortlist([candidate])
    entry = report.entries[0]
    assert entry.status == LeaderStatus.REJECTED
    assert LeaderRejectReason.PNL_CONCENTRATION_TOO_HIGH.value in entry.refusal_reasons

@pytest.mark.contract
def test_contract_leaderboard_selector_target_count():
    """
    Contract: Only the top N (target_count) should be SHORTLISTED, others WATCH_ONLY.
    """
    config = LeaderboardSelectionConfig(target_count=2)
    candidates = [
        LeaderCandidateInput(
            wallet_address=f"0x{i:040}",
            history_days=10,
            closed_pnl_points=20,
            consistency_score=100.0,
            sample_confidence=100.0
        )
        for i in range(1, 5)
    ]
    report = select_leaderboard_shortlist(candidates, config=config)
    shortlisted = [e for e in report.entries if e.status == LeaderStatus.SHORTLISTED]
    watch_only = [e for e in report.entries if e.status == LeaderStatus.WATCH_ONLY]
    assert len(shortlisted) == 2
    assert len(watch_only) == 2
