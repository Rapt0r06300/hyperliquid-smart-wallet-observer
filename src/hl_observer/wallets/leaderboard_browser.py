from __future__ import annotations

from hl_observer.wallets.leaderboard_models import LeaderboardResult, LeaderboardSourceStatus


async def scrape_leaderboard_with_browser(*, period: str = "30D", dry_run: bool = True) -> LeaderboardResult:
    """Reserved for a guarded Playwright implementation; never guesses addresses."""
    return LeaderboardResult(
        period=period,
        method="browser",
        status=LeaderboardSourceStatus.IMPORT_REQUIRED,
        notes=[
            "browser_extractor_prepared_not_active",
            "aucune adresse complete n'est inventee depuis une adresse tronquee",
            "IMPORT_REQUIRED",
        ],
    )
