from __future__ import annotations

import re
from collections.abc import Callable
from typing import Any

import httpx
from pydantic import BaseModel, Field, field_validator
from sqlalchemy.orm import Session, sessionmaker

from hl_observer.config.settings import Settings
from hl_observer.hyperliquid.endpoints import info_url_for_settings
from hl_observer.hyperliquid.rest_info_client import (
    HyperliquidInfoClient,
    build_all_mids_payload,
    build_candle_snapshot_payload,
    build_frontend_open_orders_payload,
    build_l2_book_payload,
    build_open_orders_payload,
    build_order_status_payload,
    build_user_fills_by_time_payload,
    build_user_fills_payload,
)
from hl_observer.markets.market_selector import select_markets_for_scan
from hl_observer.markets.universe import build_market_universe, fetch_market_universe
from hl_observer.storage.database import create_session_factory, create_sqlite_engine
from hl_observer.storage.repositories import CollectionRepository
from hl_observer.utils.time import now_ms

WALLET_RE = re.compile(r"^0x[a-fA-F0-9]{40}$")


class InvalidWalletAddress(ValueError):
    pass


def validate_wallet_address(address: str) -> str:
    if not WALLET_RE.fullmatch(address):
        raise InvalidWalletAddress("wallet address must be 0x followed by 40 hex characters")
    return address


class CollectionPlan(BaseModel):
    fetch: bool = False
    dry_run: bool = False
    store_raw: bool = True
    coins: list[str] = Field(default_factory=list)
    all_coins: bool = False
    include_altcoins: bool = True
    max_coins: int | None = None
    coins_from_meta: bool = False
    coins_from_all_mids: bool = False
    wallets: list[str] = Field(default_factory=list)
    all_mids: bool = False
    l2_book: bool = False
    open_orders: bool = False
    frontend_open_orders: bool = False
    user_fills: bool = False
    user_fills_by_time: bool = False
    candles: bool = False
    interval: str = "1m"
    start_ms: int | None = None
    end_ms: int | None = None
    oid_or_cloid: str | int | None = None
    limit_pages: int = 5
    page_window_ms: int = 86_400_000

    @field_validator("wallets")
    @classmethod
    def wallets_must_be_hyperliquid_addresses(cls, wallets: list[str]) -> list[str]:
        return [validate_wallet_address(wallet) for wallet in wallets]

    @field_validator("coins")
    @classmethod
    def coins_must_be_uppercase(cls, coins: list[str]) -> list[str]:
        return [coin.upper() for coin in coins]

    def requested_items(self) -> list[str]:
        items: list[str] = []
        if self.all_mids:
            items.append("allMids")
        if self.l2_book:
            items.extend(f"l2Book:{coin}" for coin in self.coins)
        for wallet in self.wallets:
            if self.open_orders:
                items.append(f"openOrders:{wallet}")
            if self.frontend_open_orders:
                items.append(f"frontendOpenOrders:{wallet}")
            if self.user_fills:
                items.append(f"userFills:{wallet}")
            if self.user_fills_by_time:
                items.append(f"userFillsByTime:{wallet}")
            if self.oid_or_cloid is not None:
                items.append(f"orderStatus:{wallet}:{self.oid_or_cloid}")
        if self.candles:
            items.extend(f"candleSnapshot:{coin}:{self.interval}" for coin in self.coins)
        return items


class CollectionResult(BaseModel):
    run_id: int | None = None
    planned_items: list[str] = Field(default_factory=list)
    fetched_items: int = 0
    raw_events_stored: int = 0
    errors_count: int = 0
    dry_run: bool = False


def build_default_collection_plan(
    *,
    settings: Settings,
    fetch: bool,
    dry_run: bool,
    store_raw: bool | None,
    coins: list[str] | None,
    all_coins: bool = False,
    include_altcoins: bool = True,
    max_coins: int | None = None,
    coins_from_meta: bool = False,
    coins_from_all_mids: bool = False,
    wallets: list[str] | None,
    all_mids: bool,
    l2_book: bool,
    open_orders: bool,
    frontend_open_orders: bool,
    user_fills: bool,
    user_fills_by_time: bool,
    candles: bool,
    interval: str,
    start_ms: int | None,
    end_ms: int | None,
    oid_or_cloid: str | None,
    limit_pages: int | None,
) -> CollectionPlan:
    selected_coins = coins or settings.collection.default_coins
    no_explicit_work = not any(
        [
            all_mids,
            l2_book,
            open_orders,
            frontend_open_orders,
            user_fills,
            user_fills_by_time,
            candles,
            oid_or_cloid is not None,
        ]
    )
    return CollectionPlan(
        fetch=fetch,
        dry_run=dry_run or not fetch,
        store_raw=settings.collection.store_raw_events if store_raw is None else store_raw,
        coins=selected_coins,
        all_coins=all_coins,
        include_altcoins=include_altcoins,
        max_coins=max_coins,
        coins_from_meta=coins_from_meta,
        coins_from_all_mids=coins_from_all_mids,
        wallets=wallets or [],
        all_mids=True if no_explicit_work else all_mids,
        l2_book=True if no_explicit_work else l2_book,
        open_orders=open_orders,
        frontend_open_orders=frontend_open_orders,
        user_fills=user_fills,
        user_fills_by_time=user_fills_by_time,
        candles=candles,
        interval=interval,
        start_ms=start_ms,
        end_ms=end_ms,
        oid_or_cloid=oid_or_cloid,
        limit_pages=limit_pages or settings.collection.max_user_fills_pages,
        page_window_ms=settings.collection.user_fills_page_window_ms,
    )


async def run_collection_once(
    plan: CollectionPlan,
    settings: Settings,
    *,
    client: HyperliquidInfoClient | None = None,
    session_factory: sessionmaker | Callable[[], Session] | None = None,
) -> CollectionResult:
    if plan.all_coins or plan.coins_from_meta or plan.coins_from_all_mids:
        plan = await _resolve_multi_asset_plan(plan, settings, client=client)
    result = CollectionResult(planned_items=plan.requested_items(), dry_run=plan.dry_run)
    if plan.dry_run:
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

    client_context = client if owns_client else _null_async_context(client)
    async with client_context as active_client:
        with session_factory() as session:
            repo = CollectionRepository(session)
            run = repo.create_collection_run(
                mode="fetch",
                wallets_count=len(plan.wallets),
                coins_count=len(plan.coins),
                notes="read-only collect-once",
            )
            result.run_id = run.id
            try:
                await _collect_plan(active_client, repo, run.id, plan, result)
            finally:
                repo.finish_collection_run(run, success=result.errors_count == 0, errors_count=result.errors_count)
                session.commit()
    return result


async def _resolve_multi_asset_plan(
    plan: CollectionPlan,
    settings: Settings,
    *,
    client: HyperliquidInfoClient | None = None,
) -> CollectionPlan:
    if plan.dry_run:
        universe = build_market_universe(settings)
    else:
        universe, _meta_payload, _all_mids_payload = await fetch_market_universe(settings, client=client)
    selection = select_markets_for_scan(
        universe,
        settings,
        max_coins=plan.max_coins,
        include_altcoins=plan.include_altcoins,
    )
    return plan.model_copy(update={"coins": selection.coins})


class _null_async_context:
    def __init__(self, client: HyperliquidInfoClient) -> None:
        self.client = client

    async def __aenter__(self) -> HyperliquidInfoClient:
        return self.client

    async def __aexit__(self, *_exc: object) -> None:
        return None


async def _collect_plan(
    client: HyperliquidInfoClient,
    repo: CollectionRepository,
    run_id: int,
    plan: CollectionPlan,
    result: CollectionResult,
) -> None:
    if plan.all_mids:
        await _record_call(
            repo,
            run_id,
            plan,
            result,
            item_type="allMids",
            request_payload=build_all_mids_payload(),
            call=lambda: client.all_mids(),
            on_success=repo.store_market_snapshot_from_all_mids,
        )

    if plan.l2_book:
        for coin in plan.coins:
            await _record_call(
                repo,
                run_id,
                plan,
                result,
                item_type="l2Book",
                request_payload=build_l2_book_payload(coin),
                coin=coin,
                call=lambda coin=coin: client.l2_book(coin),
                on_success=lambda payload, coin=coin: repo.store_orderbook_snapshot(coin, payload),
            )

    for wallet in plan.wallets:
        if plan.open_orders:
            await _record_call(
                repo,
                run_id,
                plan,
                result,
                item_type="openOrders",
                request_payload=build_open_orders_payload(wallet),
                wallet_address=wallet,
                call=lambda wallet=wallet: client.open_orders(wallet),
                on_success=lambda payload, wallet=wallet: repo.store_open_orders(wallet, payload),
            )
        if plan.frontend_open_orders:
            await _record_call(
                repo,
                run_id,
                plan,
                result,
                item_type="frontendOpenOrders",
                request_payload=build_frontend_open_orders_payload(wallet),
                wallet_address=wallet,
                call=lambda wallet=wallet: client.frontend_open_orders(wallet),
                on_success=lambda payload, wallet=wallet: repo.store_open_orders(wallet, payload),
            )
        if plan.user_fills:
            await _record_call(
                repo,
                run_id,
                plan,
                result,
                item_type="userFills",
                request_payload=build_user_fills_payload(wallet),
                wallet_address=wallet,
                call=lambda wallet=wallet: client.user_fills(wallet),
                on_success=lambda payload, wallet=wallet: repo.store_fills(wallet, payload),
            )
        if plan.user_fills_by_time:
            end_ms = plan.end_ms or now_ms()
            start_ms = plan.start_ms or (end_ms - plan.page_window_ms)
            page_index = 0
            async for page in client.iter_user_fills_by_time(
                wallet,
                start_ms,
                end_ms,
                page_window_ms=plan.page_window_ms,
                max_pages=plan.limit_pages,
            ):
                page_index += 1
                request_payload = build_user_fills_by_time_payload(wallet, start_ms, end_ms)
                repo.add_collection_item(
                    run_id=run_id,
                    item_type=f"userFillsByTime:{page_index}",
                    wallet_address=wallet,
                    status="ok",
                )
                if plan.store_raw:
                    repo.store_raw_event(
                        source="hyperliquid",
                        endpoint="/info",
                        request_type="userFillsByTime",
                        request_payload=request_payload,
                        response_payload=page,
                        wallet_address=wallet,
                    )
                    result.raw_events_stored += 1
                repo.store_fills(wallet, page)
                result.fetched_items += 1
        if plan.oid_or_cloid is not None:
            await _record_call(
                repo,
                run_id,
                plan,
                result,
                item_type="orderStatus",
                request_payload=build_order_status_payload(wallet, plan.oid_or_cloid),
                wallet_address=wallet,
                call=lambda wallet=wallet: client.order_status(wallet, plan.oid_or_cloid),
            )

    if plan.candles:
        end_ms = plan.end_ms or now_ms()
        start_ms = plan.start_ms or (end_ms - plan.page_window_ms)
        for coin in plan.coins:
            await _record_call(
                repo,
                run_id,
                plan,
                result,
                item_type="candleSnapshot",
                request_payload=build_candle_snapshot_payload(coin, plan.interval, start_ms, end_ms),
                coin=coin,
                call=lambda coin=coin: client.candle_snapshot(coin, plan.interval, start_ms, end_ms),
                on_success=lambda payload, coin=coin: repo.store_candles(coin, payload),
            )


async def _record_call(
    repo: CollectionRepository,
    run_id: int,
    plan: CollectionPlan,
    result: CollectionResult,
    *,
    item_type: str,
    request_payload: dict[str, Any],
    call: Callable[[], Any],
    wallet_address: str | None = None,
    coin: str | None = None,
    on_success: Callable[[Any], Any] | None = None,
) -> None:
    started = now_ms()
    try:
        payload = await call()
    except Exception as exc:  # noqa: BLE001 - stored for audit instead of hidden.
        error_message = str(exc)
        result.errors_count += 1
        repo.update_source_health(
            f"hyperliquid_info:{item_type}",
            is_success=False,
            error_message=error_message,
        )
        repo.add_collection_item(
            run_id=run_id,
            item_type=item_type,
            wallet_address=wallet_address,
            coin=coin,
            status="error",
            error_message=error_message,
        )
        repo.store_api_health(
            service=f"hyperliquid_info:{item_type}",
            ok=False,
            latency_ms=now_ms() - started,
            error=error_message,
        )
        if plan.store_raw:
            repo.store_raw_event(
                source="hyperliquid",
                endpoint="/info",
                request_type=request_payload["type"],
                request_payload=request_payload,
                response_payload={"error": error_message},
                wallet_address=wallet_address,
                coin=coin,
                success=False,
                error_message=error_message,
            )
            result.raw_events_stored += 1
        return

    repo.add_collection_item(
        run_id=run_id,
        item_type=item_type,
        wallet_address=wallet_address,
        coin=coin,
        status="ok",
    )
    repo.update_source_health(
        f"hyperliquid_info:{item_type}",
        is_success=True,
    )
    if item_type == "userFills" or item_type.startswith("userFillsByTime"):
        repo.update_source_health(
            "leader_fills",
            is_success=True,
        )

    repo.store_api_health(
        service=f"hyperliquid_info:{item_type}",
        ok=True,
        latency_ms=now_ms() - started,
    )
    if plan.store_raw:
        repo.store_raw_event(
            source="hyperliquid",
            endpoint="/info",
            request_type=request_payload["type"],
            request_payload=request_payload,
            response_payload=payload.model_dump() if hasattr(payload, "model_dump") else payload,
            wallet_address=wallet_address,
            coin=coin,
        )
        result.raw_events_stored += 1
    if on_success is not None:
        on_success(payload)
    result.fetched_items += 1
