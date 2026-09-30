from __future__ import annotations

import asyncio

from hl_observer.config.settings import Settings
from hl_observer.wallets.leaderboard_browser import scrape_leaderboard_with_browser
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


def test_browser_source_stays_fail_closed_until_extractor_is_active() -> None:
    result = asyncio.run(scrape_leaderboard_with_browser(period="7D", dry_run=False))

    assert result.period == "7D"
    assert result.method == "browser"
    assert result.status == LeaderboardSourceStatus.IMPORT_REQUIRED
    assert result.full_addresses_found == 0
    assert result.candidates_created == 0
    assert "browser_extractor_prepared_not_active" in result.notes


def test_dom_without_html_stays_fail_closed() -> None:
    result = asyncio.run(
        scrape_leaderboard(
            Settings(),
            method="dom",
            dom_html=None,
        )
    )

    assert result.status == LeaderboardSourceStatus.IMPORT_REQUIRED
    assert result.method == "dom"
    assert result.notes == ["dom_extractor_requires_html_fixture_or_browser_source"]
