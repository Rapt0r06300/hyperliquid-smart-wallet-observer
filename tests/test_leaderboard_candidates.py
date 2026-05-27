from hl_observer.wallets.leaderboard_models import LeaderboardCandidate
from hl_observer.wallets.top_wallet_ranker import rank_top_wallets


VALID = "0x" + "d" * 40


def test_truncated_address_never_creates_top_wallet():
    ranked = rank_top_wallets(
        [
            LeaderboardCandidate(wallet_address="0x393d...2109", leaderboard_score=100),
            LeaderboardCandidate(wallet_address=VALID, leaderboard_score=90),
        ],
        target=500,
    )

    assert [item.wallet_address for item in ranked] == [VALID]


def test_top500_does_not_count_truncated_rows():
    ranked = rank_top_wallets([LeaderboardCandidate(wallet_address="0x393d...2109", leaderboard_score=100)])

    assert ranked == []
