from __future__ import annotations

import asyncio

from sqlalchemy.orm import Session

from hl_observer.config.settings import Settings
from hl_observer.wallets.leaderboard_browser import scrape_leaderboard_with_browser
from hl_observer.wallets.leaderboard_import import store_leaderboard_result
from hl_observer.wallets.leaderboard_models import LeaderboardResult, LeaderboardSourceStatus
from hl_observer.wallets.leaderboard_network_probe import probe_leaderboard_network


async def scrape_leaderboard(
    settings: Settings,
    *,
    period: str = "30D",
    method: str = "auto",
    dry_run: bool = True,
    store: bool = False,
    session: Session | None = None,
    target: int = 500,
) -> LeaderboardResult:
    method = method.lower()
    if method in {"network", "api", "auto"}:
        result = await probe_leaderboard_network(
            period=period,
            target=target,
            timeout_seconds=settings.wallet_bootstrap.source_timeout_seconds,
            dry_run=dry_run,
        )
    elif method == "browser":
        result = await scrape_leaderboard_with_browser(period=period, dry_run=dry_run)
    elif method == "dom":
        result = LeaderboardResult(
            period=period,
            method="dom",
            status=LeaderboardSourceStatus.IMPORT_REQUIRED,
            notes=["dom_extractor_requires_html_fixture_or_browser_source"],
        )
    else:
        result = LeaderboardResult(
            period=period,
            method=method,
            status=LeaderboardSourceStatus.IMPORT_REQUIRED,
            notes=["unsupported_method_import_required"],
        )
    result.method = method
    if store and session is not None and not dry_run:
        store_leaderboard_result(session, result, source_method=method)
    return result


def scrape_leaderboard_sync(*args, **kwargs) -> LeaderboardResult:
    return asyncio.run(scrape_leaderboard(*args, **kwargs))
