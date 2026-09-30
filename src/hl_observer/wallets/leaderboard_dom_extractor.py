from __future__ import annotations

from hl_observer.wallets.leaderboard_full_address_extractor import extract_wallet_address_values
from hl_observer.wallets.leaderboard_models import LeaderboardResult, LeaderboardSourceStatus
from hl_observer.wallets.leaderboard_parser import parse_leaderboard_records


def extract_leaderboard_dom(
    html: str,
    *,
    period: str = "30D",
    source_method: str = "dom",
) -> LeaderboardResult:
    extracted = extract_wallet_address_values(html)
    rows = parse_leaderboard_records(
        [{"address": address} for address in extracted.full_addresses]
        + [{"address": address} for address in extracted.truncated_addresses],
        period=period,
        source_method=source_method,
        extraction_method="dom",
        source_confidence_score=65.0,
    )
    status = LeaderboardSourceStatus.OK if extracted.full_addresses else LeaderboardSourceStatus.IMPORT_REQUIRED
    if extracted.truncated_addresses and not extracted.full_addresses:
        status = LeaderboardSourceStatus.ONLY_TRUNCATED_ADDRESSES
    return LeaderboardResult.from_rows(rows, period=period, method="dom", status=status)
