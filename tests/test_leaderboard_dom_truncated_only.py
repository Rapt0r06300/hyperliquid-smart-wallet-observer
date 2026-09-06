from __future__ import annotations

from hl_observer.wallets.leaderboard_dom_extractor import extract_leaderboard_dom
from hl_observer.wallets.leaderboard_models import LeaderboardSourceStatus


def test_dom_truncated_only_is_fail_closed() -> None:
    result = extract_leaderboard_dom("leader 0x1234...abcd")

    assert result.status == LeaderboardSourceStatus.ONLY_TRUNCATED_ADDRESSES
    assert result.full_addresses_found == 0
    assert result.truncated_addresses_seen == 1
