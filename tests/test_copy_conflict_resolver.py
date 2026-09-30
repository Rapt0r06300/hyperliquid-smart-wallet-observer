from hl_observer.copy_wallet.copy_conflict_resolver import (
    LeaderVote,
    resolve_copy_conflict,
    resolve_copy_conflicts_by_coin,
)


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


def test_mixed_coin_votes_never_manufacture_one_cross_market_consensus():
    decision = resolve_copy_conflict(
        [
            LeaderVote(wallet="0x1", coin="BTC", side="LONG", score=3.0),
            LeaderVote(wallet="0x2", coin="ETH", side="LONG", score=3.0),
        ]
    )

    assert decision.decision == "NO_TRADE"
    assert decision.coin == ""
    assert decision.reasons == ("MIXED_COIN_VOTES_REQUIRE_GROUPING",)


def test_grouped_conflicts_keep_wallets_scoped_to_each_coin():
    grouped = resolve_copy_conflicts_by_coin(
        [
            LeaderVote(wallet="0x1", coin="BTC", side="LONG", score=2.0),
            LeaderVote(wallet="0x2", coin="BTC", side="LONG", score=1.0),
            LeaderVote(wallet="0x3", coin="ETH", side="SHORT", score=4.0),
        ]
    )

    by_coin = {decision.coin: (decision, votes) for decision, votes in grouped}
    assert set(by_coin) == {"BTC", "ETH"}
    assert {vote.wallet for vote in by_coin["BTC"][1]} == {"0x1", "0x2"}
    assert {vote.wallet for vote in by_coin["ETH"][1]} == {"0x3"}
