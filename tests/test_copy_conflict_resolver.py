from hl_observer.copy_wallet.copy_conflict_resolver import LeaderVote, resolve_copy_conflict


def test_two_opposed_leaders_blocks_as_conflict():
    decision = resolve_copy_conflict(
        [
            LeaderVote(wallet="0x1", coin="HYPE", side="LONG", score=1.0),
            LeaderVote(wallet="0x2", coin="HYPE", side="SHORT", score=0.9),
        ]
    )
    assert decision.decision == "NO_TRADE"
    assert "CONFLICTING_LEADERS" in decision.reasons


def test_strong_majority_can_follow():
    decision = resolve_copy_conflict(
        [
            LeaderVote(wallet="0x1", coin="HYPE", side="LONG", score=2.0),
            LeaderVote(wallet="0x2", coin="HYPE", side="SHORT", score=0.5),
        ]
    )
    assert decision.decision == "FOLLOW"
    assert decision.winning_side == "LONG"
