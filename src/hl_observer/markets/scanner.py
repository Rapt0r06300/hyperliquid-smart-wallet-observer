from __future__ import annotations

from collections.abc import Callable
from typing import Any

from pydantic import BaseModel, Field
from sqlalchemy.orm import Session, sessionmaker

from hl_observer.config.settings import Settings
from hl_observer.hyperliquid.endpoints import info_url_for_settings
from hl_observer.hyperliquid.rest_info_client import (
    HyperliquidInfoClient,
    build_all_mids_payload,
    build_l2_book_payload,
    build_meta_payload,
)
from hl_observer.markets.coin_metrics import MarketMetricRecord, build_market_metric
from hl_observer.markets.market_selector import select_markets_for_scan
from hl_observer.markets.universe import MarketUniverse, build_market_universe, fetch_market_universe
from hl_observer.storage.database import create_session_factory, create_sqlite_engine, init_db
from hl_observer.storage.repositories import CollectionRepository


class MarketDiscoveryPlan(BaseModel):
    sources: list[str] = Field(default_factory=lambda: ["meta", "all-mids"])
    include_altcoins: bool = True
    max_coins: int | None = None
    store: bool = False
    dry_run: bool = True
    report: bool = False
    json_output: bool = False


class MarketScanPlan(BaseModel):
    coins: list[str] = Field(default_factory=list)
    all_coins: bool = False
    include_altcoins: bool = True
    max_coins: int | None = None
    l2book: bool = True
    candles: bool = False
    store: bool = False
    dry_run: bool = True
    report: bool = False

    def normalized_coins(self) -> list[str]:
        return [coin.upper() for coin in self.coins]


class MarketDiscoveryResult(BaseModel):
    coins_discovered: int = 0
    coins: list[str] = Field(default_factory=list)
    altcoins_count: int = 0
    sources_used: list[str] = Field(default_factory=list)
    stored: bool = False
    dry_run: bool = False
    notes: list[str] = Field(default_factory=list)


class MarketScanResult(BaseModel):
    coins_discovered: int = 0
    coins_scanned: int = 0
    l2books_scanned: int = 0
    candles_scanned: int = 0
    metrics_stored: int = 0
    raw_events_stored: int = 0
    errors_count: int = 0
    selected_coins: list[str] = Field(default_factory=list)
    metrics: list[MarketMetricRecord] = Field(default_factory=list)
    dry_run: bool = False
    notes: list[str] = Field(default_factory=list)


async def run_discover_markets(
    plan: MarketDiscoveryPlan,
    settings: Settings,
    *,
    client: HyperliquidInfoClient | None = None,
    session_factory: sessionmaker | Callable[[], Session] | None = None,
) -> MarketDiscoveryResult:
    init_db(settings.database_url)
    if plan.dry_run:
        universe = build_market_universe(settings)
        limited = universe.items[: plan.max_coins or settings.market_universe.max_coins_per_scan]
        return MarketDiscoveryResult(
            coins_discovered=len(limited),
            coins=[item.coin for item in limited],
            altcoins_count=sum(1 for item in limited if item.coin not in {"BTC", "ETH"}),
            sources_used=universe.sources_used,
            dry_run=True,
            notes=["dry_run_no_network", "fallback_universe_only"],
        )

    universe, meta_payload, all_mids_payload = await fetch_market_universe(settings, client=client)
    if session_factory is None:
        engine = create_sqlite_engine(settings.database_url)
        session_factory = create_session_factory(engine)
    if plan.store:
        with session_factory() as session:
            repo = CollectionRepository(session)
            run = repo.create_collection_run(
                mode="discover-markets",
                wallets_count=0,
                coins_count=len(universe.items),
                notes="read-only market universe discovery",
            )
            if meta_payload is not None:
                repo.store_raw_event(
                    source="hyperliquid",
                    endpoint="/info",
                    request_type="meta",
                    request_payload=build_meta_payload(),
                    response_payload=meta_payload,
                )
            if all_mids_payload is not None:
                repo.store_raw_event(
                    source="hyperliquid",
                    endpoint="/info",
                    request_type="allMids",
                    request_payload=build_all_mids_payload(),
                    response_payload=all_mids_payload,
                )
            for item in universe.items:
                repo.store_market_universe_item(item)
            repo.finish_collection_run(run, success=True, errors_count=0)
            session.commit()
    limited_items = universe.items[: plan.max_coins or settings.market_universe.max_coins_per_scan]
    return MarketDiscoveryResult(
        coins_discovered=len(universe.items),
        coins=[item.coin for item in limited_items],
        altcoins_count=universe.altcoins_count,
        sources_used=universe.sources_used,
        stored=plan.store,
        dry_run=False,
    )


async def run_scan_markets(
    plan: MarketScanPlan,
    settings: Settings,
    *,
    client: HyperliquidInfoClient | None = None,
    session_factory: sessionmaker | Callable[[], Session] | None = None,
) -> MarketScanResult:
    result = MarketScanResult(dry_run=plan.dry_run)
    if plan.dry_run:
        universe = build_market_universe(settings)
        selection = select_markets_for_scan(
            universe,
            settings,
            max_coins=plan.max_coins,
            include_altcoins=plan.include_altcoins,
        )
        result.coins_discovered = len(universe.items)
        result.selected_coins = selection.coins
        result.coins_scanned = len(selection.coins)
        result.notes.extend(["dry_run_no_network", *selection.notes])
        return result

    owns_client = client is None
    if client is None:
        client = HyperliquidInfoClient(
            info_url_for_settings(settings),
            timeout_seconds=settings.collection.request_timeout_seconds,
            max_retries=settings.collection.retry_count,
            backoff_base_seconds=settings.collection.retry_backoff_seconds,
        )
    if session_factory is None:
        engine = create_sqlite_engine(settings.database_url)
        session_factory = create_session_factory(engine)
    context = client if owns_client else _null_async_context(client)
    async with context as active_client:
        universe, meta_payload, all_mids_payload = await fetch_market_universe(settings, client=active_client)
        result.coins_discovered = len(universe.items)
        explicit = plan.normalized_coins()
        if explicit and not plan.all_coins:
            selected = explicit[: plan.max_coins or len(explicit)]
        else:
            selected = select_markets_for_scan(
                universe,
                settings,
                max_coins=plan.max_coins,
                include_altcoins=plan.include_altcoins,
            ).coins
        l2_limit = settings.market_universe.max_l2book_coins_per_scan
        selected_for_books = selected[:l2_limit] if plan.l2book else []
        with session_factory() as session:
            repo = CollectionRepository(session)
            run = repo.create_collection_run(
                mode="scan-markets",
                wallets_count=0,
                coins_count=len(selected),
                notes="read-only multi-asset market scan",
            )
            try:
                if plan.store:
                    if meta_payload is not None:
                        repo.store_raw_event(
                            source="hyperliquid",
                            endpoint="/info",
                            request_type="meta",
                            request_payload=build_meta_payload(),
                            response_payload=meta_payload,
                        )
                        result.raw_events_stored += 1
                    if all_mids_payload is not None:
                        repo.store_raw_event(
                            source="hyperliquid",
                            endpoint="/info",
                            request_type="allMids",
                            request_payload=build_all_mids_payload(),
                            response_payload=all_mids_payload,
                        )
                        result.raw_events_stored += 1
                    for item in universe.items:
                        repo.store_market_universe_item(item)
                for coin in selected_for_books:
                    mid = _mid_for_coin(all_mids_payload or {}, coin)
                    try:
                        book = await active_client.l2_book(coin)
                    except Exception as exc:  # noqa: BLE001 - stored below as a scan error.
                        result.errors_count += 1
                        result.notes.append(f"{coin}: {exc}")
                        if plan.store:
                            repo.store_raw_event(
                                source="hyperliquid",
                                endpoint="/info",
                                request_type="l2Book",
                                request_payload=build_l2_book_payload(coin),
                                response_payload={"error": str(exc)},
                                coin=coin,
                                success=False,
                                error_message=str(exc),
                            )
                            result.raw_events_stored += 1
                        continue
                    metric = build_market_metric(coin, settings=settings, mid_price=mid, orderbook=book)
                    result.metrics.append(metric)
                    result.l2books_scanned += 1
                    if plan.store:
                        repo.store_raw_event(
                            source="hyperliquid",
                            endpoint="/info",
                            request_type="l2Book",
                            request_payload=build_l2_book_payload(coin),
                            response_payload=book,
                            coin=coin,
                        )
                        repo.store_orderbook_snapshot(coin, book)
                        repo.store_market_metric(metric)
                        result.raw_events_stored += 1
                        result.metrics_stored += 1
                result.selected_coins = selected
                result.coins_scanned = len(selected)
            finally:
                repo.finish_collection_run(run, success=result.errors_count == 0, errors_count=result.errors_count)
                session.commit()
    return result


def format_market_discovery_report(result: MarketDiscoveryResult) -> str:
    lines = [
        "market discovery report",
        f"coins discovered: {result.coins_discovered}",
        f"altcoins discovered: {result.altcoins_count}",
        f"sources used: {', '.join(result.sources_used)}",
        f"stored: {result.stored}",
        f"dry-run: {result.dry_run}",
    ]
    if result.coins:
        lines.append(f"coins: {', '.join(result.coins[:30])}")
    if result.notes:
        lines.append(f"notes: {'; '.join(result.notes)}")
    return "\n".join(lines)


def format_market_scan_report(result: MarketScanResult) -> str:
    lines = [
        "market scan report",
        f"coins discovered: {result.coins_discovered}",
        f"coins selected: {len(result.selected_coins)}",
        f"l2Books scanned: {result.l2books_scanned}",
        f"metrics stored: {result.metrics_stored}",
        f"errors: {result.errors_count}",
        f"dry-run: {result.dry_run}",
    ]
    if result.selected_coins:
        lines.append(f"selected coins: {', '.join(result.selected_coins[:50])}")
    if result.notes:
        lines.append(f"notes: {'; '.join(result.notes)}")
    return "\n".join(lines)


class _null_async_context:
    def __init__(self, client: HyperliquidInfoClient) -> None:
        self.client = client

    async def __aenter__(self) -> HyperliquidInfoClient:
        return self.client

    async def __aexit__(self, *_exc: object) -> None:
        return None


def _mid_for_coin(all_mids_payload: dict[str, Any], coin: str) -> float | None:
    for key in (coin, coin.upper(), coin.lower()):
        if key in all_mids_payload:
            try:
                return float(all_mids_payload[key])
            except (TypeError, ValueError):
                return None
    return None

