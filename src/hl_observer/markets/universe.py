from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from hl_observer.config.settings import Settings
from hl_observer.hyperliquid.endpoints import info_url_for_settings
from hl_observer.hyperliquid.rest_info_client import HyperliquidInfoClient


class MarketUniverseItem(BaseModel):
    coin: str
    source: str
    is_active: bool = True
    is_spot: bool = False
    mid_price: float | None = None
    notes: str | None = None


class MarketUniverse(BaseModel):
    items: list[MarketUniverseItem] = Field(default_factory=list)
    sources_used: list[str] = Field(default_factory=list)
    altcoins_enabled: bool = True
    notes: list[str] = Field(default_factory=list)

    @property
    def coins(self) -> list[str]:
        return [item.coin for item in self.items]

    @property
    def altcoins_count(self) -> int:
        majors = {"BTC", "ETH"}
        return sum(1 for coin in self.coins if coin not in majors)


def extract_universe_from_meta(meta_payload: dict[str, Any], *, include_spot: bool = False) -> list[MarketUniverseItem]:
    raw_universe = meta_payload.get("universe")
    if not isinstance(raw_universe, list):
        return []
    items: list[MarketUniverseItem] = []
    for asset in raw_universe:
        if not isinstance(asset, dict):
            continue
        name = asset.get("name")
        if not name:
            continue
        is_active = not bool(asset.get("isDelisted", False))
        is_spot = bool(asset.get("isSpot", False))
        if is_spot and not include_spot:
            continue
        items.append(
            MarketUniverseItem(
                coin=str(name).upper(),
                source="meta",
                is_active=is_active,
                is_spot=is_spot,
                notes="from_hyperliquid_meta",
            )
        )
    return items


def extract_universe_from_all_mids(all_mids_payload: dict[str, Any]) -> list[MarketUniverseItem]:
    items: list[MarketUniverseItem] = []
    for coin, raw_mid in all_mids_payload.items():
        try:
            mid_price = float(raw_mid)
        except (TypeError, ValueError):
            mid_price = None
        items.append(
            MarketUniverseItem(
                coin=str(coin).upper(),
                source="allMids",
                is_active=True,
                mid_price=mid_price,
                notes="fallback_from_all_mids",
            )
        )
    return items


def build_market_universe(
    settings: Settings,
    *,
    meta_payload: dict[str, Any] | None = None,
    all_mids_payload: dict[str, Any] | None = None,
) -> MarketUniverse:
    excluded = {coin.upper() for coin in settings.market_universe.excluded_coins}
    merged: dict[str, MarketUniverseItem] = {}
    sources_used: list[str] = []
    if meta_payload and settings.market_universe.discover_from_meta:
        sources_used.append("meta")
        for item in extract_universe_from_meta(meta_payload, include_spot=settings.market_universe.include_spot):
            merged[item.coin] = item
    if all_mids_payload and settings.market_universe.discover_from_all_mids:
        sources_used.append("allMids")
        for item in extract_universe_from_all_mids(all_mids_payload):
            existing = merged.get(item.coin)
            if existing is None:
                merged[item.coin] = item
            else:
                existing.mid_price = item.mid_price
                existing.notes = "meta_with_all_mids_price"
    if not merged:
        sources_used.append("fallback")
        for coin in settings.market_universe.default_fallback_coins:
            merged[coin.upper()] = MarketUniverseItem(
                coin=coin.upper(),
                source="fallback",
                notes="config_default_fallback_coin",
            )
    items = [
        item
        for item in merged.values()
        if item.coin not in excluded
        and item.is_active
        and (settings.market_universe.altcoins_enabled or item.coin in {"BTC", "ETH"})
        and (item.mid_price is None or item.mid_price >= settings.market_universe.min_mid_price_usdc)
    ]
    items.sort(key=lambda item: _coin_priority(item.coin))
    return MarketUniverse(
        items=items,
        sources_used=sources_used,
        altcoins_enabled=settings.market_universe.altcoins_enabled,
    )


async def fetch_market_universe(
    settings: Settings,
    *,
    client: HyperliquidInfoClient | None = None,
) -> tuple[MarketUniverse, dict[str, Any] | None, dict[str, Any] | None]:
    owns_client = client is None
    if client is None:
        client = HyperliquidInfoClient(
            info_url_for_settings(settings),
            timeout_seconds=settings.collection.request_timeout_seconds,
            max_retries=settings.collection.retry_count,
            backoff_base_seconds=settings.collection.retry_backoff_seconds,
        )
    meta_payload: dict[str, Any] | None = None
    all_mids_payload: dict[str, Any] | None = None
    context = client if owns_client else _null_async_context(client)
    async with context as active_client:
        if settings.market_universe.discover_from_meta:
            meta_payload = await active_client.meta()
        if settings.market_universe.discover_from_all_mids:
            all_mids_payload = await active_client.all_mids()
    return build_market_universe(
        settings,
        meta_payload=meta_payload,
        all_mids_payload=all_mids_payload,
    ), meta_payload, all_mids_payload


class _null_async_context:
    def __init__(self, client: HyperliquidInfoClient) -> None:
        self.client = client

    async def __aenter__(self) -> HyperliquidInfoClient:
        return self.client

    async def __aexit__(self, *_exc: object) -> None:
        return None


def _coin_priority(coin: str) -> tuple[int, str]:
    majors = ["BTC", "ETH", "SOL", "HYPE"]
    if coin in majors:
        return (majors.index(coin), coin)
    return (len(majors), coin)

