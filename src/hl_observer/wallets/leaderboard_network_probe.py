from __future__ import annotations

from typing import Any

import httpx

from hl_observer.wallets.leaderboard_full_address_extractor import extract_wallet_address_values
from hl_observer.wallets.leaderboard_models import LeaderboardResult, LeaderboardSourceStatus
from hl_observer.wallets.leaderboard_parser import parse_leaderboard_records

LEADERBOARD_URL = "https://app.hyperliquid.xyz/leaderboard"
STATS_LEADERBOARD_URL = "https://stats-data.hyperliquid.xyz/Mainnet/leaderboard"
PERIOD_TO_STATS_WINDOW = {
    "1D": "day",
    "7D": "week",
    "30D": "month",
    "ALL": "allTime",
}


async def probe_leaderboard_network(
    *,
    url: str = LEADERBOARD_URL,
    period: str = "30D",
    target: int = 500,
    timeout_seconds: float = 15.0,
    dry_run: bool = True,
) -> LeaderboardResult:
    """Best-effort public probe. Dry-run never performs network IO."""
    if dry_run:
        return LeaderboardResult(
            period=period,
            method="network",
            status=LeaderboardSourceStatus.IMPORT_REQUIRED,
            notes=[
                "dry_run_no_network",
                "IMPORT_REQUIRED si la page publique ne fournit pas d'adresses completes.",
            ],
        )
    stats_error: str | None = None
    try:
        async with httpx.AsyncClient(timeout=timeout_seconds, follow_redirects=True) as client:
            response = await client.get(
                STATS_LEADERBOARD_URL,
                headers={
                    "accept": "application/json",
                    "user-agent": "hl-observer-read-only/0.1",
                },
            )
            response.raise_for_status()
            payload = response.json()
        records = normalize_stats_leaderboard_payload(payload, period=period, target=target)
        rows = parse_leaderboard_records(
            records,
            period=period,
            source_method="stats_data",
            extraction_method="network",
            source_confidence_score=95.0,
        )
        status = LeaderboardSourceStatus.OK if any(row.address for row in rows) else LeaderboardSourceStatus.IMPORT_REQUIRED
        result = LeaderboardResult.from_rows(
            rows,
            period=period,
            method="network",
            status=status,
            notes=[
                "stats_data_leaderboard_completed",
                f"source={STATS_LEADERBOARD_URL}",
                "public_app_source_full_addresses_only",
            ],
        )
        return result
    except (httpx.HTTPError, ValueError) as exc:
        stats_error = str(exc)

    try:
        async with httpx.AsyncClient(timeout=timeout_seconds, follow_redirects=True) as client:
            response = await client.get(url, headers={"user-agent": "hl-observer-read-only/0.1"})
            response.raise_for_status()
            payload: Any = {"url": str(response.url), "body": response.text}
    except httpx.HTTPError as exc:
        return LeaderboardResult(
            period=period,
            method="network",
            status=LeaderboardSourceStatus.SOURCE_UNAVAILABLE,
            error_message=str(exc),
            notes=[f"stats_data_error={stats_error}"] if stats_error else [],
        )

    extracted = extract_wallet_address_values(payload)
    rows = parse_leaderboard_records(
        [{"address": address} for address in extracted.full_addresses]
        + [{"address": address} for address in extracted.truncated_addresses],
        period=period,
        source_method="network",
        extraction_method="network",
        source_confidence_score=70.0,
    )
    status = LeaderboardSourceStatus.OK if extracted.full_addresses else LeaderboardSourceStatus.IMPORT_REQUIRED
    if extracted.truncated_addresses and not extracted.full_addresses:
        status = LeaderboardSourceStatus.ONLY_TRUNCATED_ADDRESSES
    return LeaderboardResult.from_rows(
        rows,
        period=period,
        method="network",
        status=status,
        notes=["app_page_network_probe_completed", f"stats_data_error={stats_error}"] if stats_error else ["app_page_network_probe_completed"],
    )


def normalize_stats_leaderboard_payload(
    payload: dict[str, Any],
    *,
    period: str = "30D",
    target: int = 500,
) -> list[dict[str, Any]]:
    rows = payload.get("leaderboardRows")
    if not isinstance(rows, list):
        raise ValueError("stats leaderboard payload missing leaderboardRows")
    window = PERIOD_TO_STATS_WINDOW.get(period.upper(), "month")
    normalized: list[dict[str, Any]] = []
    for index, row in enumerate(rows[: max(0, target)], start=1):
        if not isinstance(row, dict):
            continue
        performance = _window_performance(row.get("windowPerformances"), window)
        normalized.append(
            {
                "rank": index,
                "ethAddress": row.get("ethAddress"),
                "accountValue": row.get("accountValue"),
                "pnl": performance.get("pnl"),
                "roi": _roi_ratio_to_percent(performance.get("roi")),
                "volume": performance.get("vlm") or performance.get("volume"),
                "displayName": row.get("displayName"),
                "source": STATS_LEADERBOARD_URL,
                "period_window": window,
            }
        )
    return normalized


def _window_performance(value: Any, window: str) -> dict[str, Any]:
    if isinstance(value, dict):
        selected = value.get(window) or {}
        return selected if isinstance(selected, dict) else {}
    if isinstance(value, list):
        for item in value:
            if not isinstance(item, (list, tuple)) or len(item) != 2:
                continue
            key, data = item
            if key == window and isinstance(data, dict):
                return data
    return {}


def _roi_ratio_to_percent(value: Any) -> Any:
    if value in (None, ""):
        return value
    try:
        return float(value) * 100.0
    except (TypeError, ValueError):
        return value
