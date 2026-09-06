from __future__ import annotations

import asyncio

from hl_observer.config.settings import Settings
from hl_observer.wallets.leaderboard_dom_extractor import extract_leaderboard_dom
from hl_observer.wallets.leaderboard_models import LeaderboardSourceStatus
from hl_observer.wallets.leaderboard_source import scrape_leaderboard


def test_dom_truncated_only_is_fail_closed() -> None:
    result = extract_leaderboard_dom("leader 0x1234...abcd")

    assert result.status == LeaderboardSourceStatus.ONLY_TRUNCATED_ADDRESSES
    assert result.full_addresses_found == 0
    assert result.truncated_addresses_seen == 1


def test_dom_truncated_only_is_reachable_through_canonical_source() -> None:
    result = asyncio.run(
        scrape_leaderboard(
            Settings(),
            method="dom",
            dom_html="leader 0x1234...abcd",
        )
    )

    assert result.status == LeaderboardSourceStatus.ONLY_TRUNCATED_ADDRESSES
    assert result.full_addresses_found == 0
    assert result.truncated_addresses_seen == 1
