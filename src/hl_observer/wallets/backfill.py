from __future__ import annotations

from collections.abc import Callable
from typing import Any

from pydantic import BaseModel, Field, field_validator
from sqlalchemy.orm import Session, sessionmaker

from hl_observer.collection.collector import InvalidWalletAddress, validate_wallet_address
from hl_observer.config.settings import Settings
from hl_observer.hyperliquid.endpoints import info_url_for_settings
from hl_observer.hyperliquid.rest_info_client import (
    HyperliquidInfoClient,
    build_all_mids_payload,
    build_frontend_open_orders_payload,
    build_l2_book_payload,
    build_open_orders_payload,
    build_user_fills_by_time_payload,
    build_user_fills_payload,
)
from hl_observer.storage.database import create_session_factory, create_sqlite_engine
from hl_observer.storage.repositories import CollectionRepository, stable_payload_hash
from hl_observer.utils.time import now_ms
from hl_observer.wallets.activity_summary import summarize_wallet_activity
from hl_observer.wallets.per_coin_scoring import score_wallet_coin
from hl_observer.wallets.wallet_coin_profile import build_wallet_coin_profiles
from hl_observer.wallets.position_rebuilder import rebuild_positions_from_fills
from hl_observer.wallets.profiler import profile_from_metrics
from hl_observer.wallets.scoring import score_wallet

DEFAULT_BACKFILL_WINDOW_MS = 7 * 24 * 60 * 60 * 1000


class WalletBackfillPlan(BaseModel):
    fetch: bool = True
    dry_run: bool = False
    store_raw: bool = True
    wallets: list[str] = Field(default_factory=list)
    coins: list[str] = Field(default_factory=list)
    start_ms: int | None = None
    end_ms: int | None = None
    limit_pages: int = 5
    page_window_ms: int = 86_400_000
    include_recent_fills: bool = True
    include_fills_by_time: bool = True
    include_open_orders: bool = True
    include_frontend_open_orders: bool = True
    include_market_snapshots: bool = False
    rebuild_positions: bool = True
    compute_position_deltas: bool = True
    report: bool = False

    @field_validator("wallets")
    @classmethod
    def wallets_must_be_hyperliquid_addresses(cls, wallets: list[str]) -> list[str]:
        return [validate_wallet_address(wallet) for wallet in wallets]

    @field_validator("coins")
    @classmethod
    def coins_must_be_uppercase(cls, coins: list[str]) -> list[str]:
        return [coin.upper() for coin in coins]

    def effective_end_ms(self) -> int:
        return self.end_ms or now_ms()

    def effective_start_ms(self) -> int:
        if self.start_ms is not None:
            return self.start_ms
        return max(0, self.effective_end_ms() - DEFAULT_BACKFILL_WINDOW_MS)

    def requested_items(self) -> list[str]:
        items: list[str] = []
        wallets = self.wallets or ["<dry-run-wallet>"]
        for wallet in wallets:
            if self.include_recent_fills:
                items.append(f"userFills:{wallet}")
            if self.include_fills_by_time:
                items.append(f"userFillsByTime:{wallet}")
            if self.include_open_orders:
                items.append(f"openOrders:{wallet}")
            if self.include_frontend_open_orders:
                items.append(f"frontendOpenOrders:{wallet}")
            if self.rebuild_positions:
                items.append(f"positions:{wallet}")
            if self.compute_position_deltas:
                items.append(f"positionDeltas:{wallet}")
        if self.include_market_snapshots:
            items.append("allMids")
            items.extend(f"l2Book:{coin}" for coin in self.coins)
        return items


class WalletBackfillResult(BaseModel):
    run_id: int | None = None
    wallet_backfill_run_ids: list[int] = Field(default_factory=list)
    planned_items: list[str] = Field(default_factory=list)
    wallets_count: int = 0
    fetched_items: int = 0
    fills_stored: int = 0
    open_orders_stored: int = 0
    raw_events_stored: int = 0
    market_snapshots_stored: int = 0
    positions_rebuilt: int = 0
    position_deltas_created: int = 0
    activity_summaries_stored: int = 0
    errors_count: int = 0
    confidence_score: float = 0.0
    dry_run: bool = False
    start_ms: int | None = None
    end_ms: int | None = None
    actions: dict[str, int] = Field(default_factory=dict)
    fills_by_coin: dict[str, int] = Field(default_factory=dict)
    deltas_by_coin: dict[str, int] = Field(default_factory=dict)
    wallet_coin_profiles_created: int = 0
    wallet_coin_scores_created: int = 0
    best_coin_by_wallet: dict[str, str] = Field(default_factory=dict)
    notes: list[str] = Field(default_factory=list)


def build_wallet_backfill_plan(
    *,
    settings: Settings,
    wallets: list[str] | None,
    fetch: bool,
    dry_run: bool,
    store_raw: bool | None,
    start_ms: int | None,
    end_ms: int | None,
    limit_pages: int | None,
    page_window_ms: int | None,
    coins: list[str] | None = None,
    recent_fills: bool = True,
    fills_by_time: bool = True,
    open_orders: bool = True,
    frontend_open_orders: bool = True,
    market_snapshots: bool = False,
    rebuild_positions: bool = True,
    position_deltas: bool = True,
    report: bool = False,
) -> WalletBackfillPlan:
    selected_wallets = wallets or []
    if not selected_wallets and not dry_run:
        raise InvalidWalletAddress("at least one wallet address is required for wallet-backfill")
    return WalletBackfillPlan(
        fetch=fetch,
        dry_run=dry_run or not fetch,
        store_raw=settings.collection.store_raw_events if store_raw is None else store_raw,
        wallets=selected_wallets,
        coins=coins or settings.collection.default_coins,
        start_ms=start_ms,
        end_ms=end_ms,
        limit_pages=limit_pages or settings.collection.max_user_fills_pages,
        page_window_ms=page_window_ms or settings.collection.user_fills_page_window_ms,
        include_recent_fills=recent_fills,
        include_fills_by_time=fills_by_time,
        include_open_orders=open_orders,
        include_frontend_open_orders=frontend_open_orders,
        include_market_snapshots=market_snapshots,
        rebuild_positions=rebuild_positions,
        compute_position_deltas=position_deltas,
        report=report,
    )


async def run_wallet_backfill(
    plan: WalletBackfillPlan,
    settings: Settings,
    *,
    client: HyperliquidInfoClient | None = None,
    session_factory: sessionmaker | Callable[[], Session] | None = None,
) -> WalletBackfillResult:
    start_ms = plan.effective_start_ms()
    end_ms = plan.effective_end_ms()
    result = WalletBackfillResult(
        planned_items=plan.requested_items(),
        wallets_count=len(plan.wallets),
        dry_run=plan.dry_run,
        start_ms=start_ms,
        end_ms=end_ms,
    )
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
                mode="wallet-backfill",
                wallets_count=len(plan.wallets),
                coins_count=len(plan.coins),
                notes="read-only wallet historical backfill",
            )
            result.run_id = run.id
            try:
                if plan.include_market_snapshots:
                    await _collect_market_snapshots(active_client, repo, run.id, plan, result)
                await _backfill_wallets(active_client, repo, run.id, plan, result, start_ms, end_ms)
            finally:
                repo.finish_collection_run(run, success=result.errors_count == 0, errors_count=result.errors_count)
                session.commit()
    return result


def format_wallet_backfill_report(result: WalletBackfillResult, plan: WalletBackfillPlan) -> str:
    lines = [
        "wallet-backfill report",
        f"wallets: {', '.join(plan.wallets) if plan.wallets else '<dry-run-wallet>'}",
        f"window: {result.start_ms} -> {result.end_ms}",
        f"fills stored: {result.fills_stored}",
        f"open orders stored: {result.open_orders_stored}",
        f"coins configured: {', '.join(plan.coins)}",
        f"coins detected: {', '.join(sorted(result.fills_by_coin)) if result.fills_by_coin else 'none'}",
        f"positions reconstructed: {result.positions_rebuilt}",
        f"deltas detected: {result.position_deltas_created}",
        f"deltas by coin: {result.deltas_by_coin or {}}",
        f"best coin by wallet: {result.best_coin_by_wallet or {}}",
        f"actions: {result.actions or {}}",
        f"confidence score: {result.confidence_score:.2f}",
        f"errors: {result.errors_count}",
        "next: run score-wallets after enough wallet history is collected",
    ]
    if result.notes:
        lines.append(f"notes: {'; '.join(sorted(set(result.notes)))}")
    if result.dry_run:
        lines.append("dry-run: no network and no database writes")
    return "\n".join(lines)


class _null_async_context:
    def __init__(self, client: HyperliquidInfoClient) -> None:
        self.client = client

    async def __aenter__(self) -> HyperliquidInfoClient:
        return self.client

    async def __aexit__(self, *_exc: object) -> None:
        return None


async def _collect_market_snapshots(
    client: HyperliquidInfoClient,
    repo: CollectionRepository,
    run_id: int,
    plan: WalletBackfillPlan,
    result: WalletBackfillResult,
) -> None:
    mids = await _record_backfill_call(
        repo,
        run_id,
        plan,
        result,
        item_type="allMids",
        request_payload=build_all_mids_payload(),
        call=lambda: client.all_mids(),
    )
    if isinstance(mids, dict):
        repo.store_market_snapshot_from_all_mids(mids)
        result.market_snapshots_stored += 1
    for coin in plan.coins:
        book = await _record_backfill_call(
            repo,
            run_id,
            plan,
            result,
            item_type="l2Book",
            request_payload=build_l2_book_payload(coin),
            coin=coin,
            call=lambda coin=coin: client.l2_book(coin),
        )
        if isinstance(book, dict):
            repo.store_orderbook_snapshot(coin, book)
            result.market_snapshots_stored += 1


async def _backfill_wallets(
    client: HyperliquidInfoClient,
    repo: CollectionRepository,
    run_id: int,
    plan: WalletBackfillPlan,
    result: WalletBackfillResult,
    start_ms: int,
    end_ms: int,
) -> None:
    for wallet in plan.wallets:
        repo.ensure_wallet(wallet)
        backfill_run = repo.create_wallet_backfill_run(
            wallet_address=wallet,
            start_ms=start_ms,
            end_ms=end_ms,
            notes="read-only wallet-backfill",
        )
        result.wallet_backfill_run_ids.append(backfill_run.id)
        wallet_errors_before = result.errors_count
        fills_for_rebuild: list[dict[str, Any]] = []
        wallet_open_orders = 0

        if plan.include_recent_fills:
            fills = await _record_backfill_call(
                repo,
                run_id,
                plan,
                result,
                item_type="userFills",
                request_payload=build_user_fills_payload(wallet),
                wallet_address=wallet,
                call=lambda wallet=wallet: client.user_fills(wallet),
            )
            if isinstance(fills, list):
                fills_for_rebuild.extend(fills)
                result.fills_stored += len(repo.store_fills(wallet, fills))

        if plan.include_fills_by_time:
            await _collect_user_fills_by_time(
                client,
                repo,
                run_id,
                plan,
                result,
                wallet,
                start_ms,
                end_ms,
                fills_for_rebuild,
            )

        unique_fills = _unique_fills(fills_for_rebuild)
        for fill in unique_fills:
            coin = str(fill.get("coin") or fill.get("coinName") or "UNKNOWN").upper()
            result.fills_by_coin[coin] = result.fills_by_coin.get(coin, 0) + 1
        rebuild = rebuild_positions_from_fills(wallet, unique_fills)
        result.notes.extend(rebuild.notes)
        if plan.rebuild_positions:
            for position in rebuild.positions:
                repo.store_position(position)
            result.positions_rebuilt += len(rebuild.positions)
        if plan.compute_position_deltas:
            stored_deltas = repo.store_position_deltas(rebuild.deltas)
            result.position_deltas_created += len(stored_deltas)
            for delta in rebuild.deltas:
                result.deltas_by_coin[delta.coin] = result.deltas_by_coin.get(delta.coin, 0) + 1
                result.actions[delta.action.value] = result.actions.get(delta.action.value, 0) + 1
        if rebuild.confidence_score:
            result.confidence_score = _rolling_average(
                result.confidence_score,
                rebuild.confidence_score,
                len(result.wallet_backfill_run_ids),
            )
        summary = summarize_wallet_activity(
            wallet_address=wallet,
            fills_count=len(unique_fills),
            deltas=rebuild.deltas,
            window_start_ms=start_ms,
            window_end_ms=end_ms,
            fills=unique_fills,
        )
        repo.store_wallet_activity_summary(summary)
        result.activity_summaries_stored += 1

        # Global wallet scoring
        metrics = {
            "trades_count": summary.closed_pnl_count,
            "fills_count": summary.fills_count,
            "closed_pnl_count": summary.closed_pnl_count,
            "active_days": int(summary.history_days),
            "history_days": summary.history_days,
            "pnl_total_usdc": summary.pnl_total_usdc,
            "pnl_net_after_fees_usdc": summary.pnl_net_after_fees_usdc,
            "win_rate": summary.win_rate,
            "profit_factor": summary.profit_factor,
            "max_drawdown_pct": summary.max_drawdown_pct,
            "top_trade_pnl_share": summary.top_trade_pnl_share,
            "coins_traded_count": summary.coins_count,
            "main_coin": summary.main_coin,
            "recent_activity_score": summary.recent_activity_score,
            "regularity_score": summary.regularity_score,
            "copyability_score": summary.copyability_score,
        }
        profile = profile_from_metrics(wallet, metrics)
        score = score_wallet(profile)
        repo.store_wallet_score(score)
        repo.ensure_wallet(wallet, status=score.status.value)

        profiles = build_wallet_coin_profiles(
            wallet,
            unique_fills,
            deltas_by_coin=result.deltas_by_coin,
            min_fills_for_score=3,
        )
        best_profile_score = -1.0
        for profile in profiles:
            score = score_wallet_coin(profile)
            profile.final_coin_score = score.final_score
            repo.store_wallet_coin_profile(profile)
            repo.store_wallet_coin_score(score)
            result.wallet_coin_profiles_created += 1
            result.wallet_coin_scores_created += 1
            if score.final_score > best_profile_score:
                best_profile_score = score.final_score
                result.best_coin_by_wallet[wallet] = profile.coin

        if plan.include_open_orders:
            orders = await _record_backfill_call(
                repo,
                run_id,
                plan,
                result,
                item_type="openOrders",
                request_payload=build_open_orders_payload(wallet),
                wallet_address=wallet,
                call=lambda wallet=wallet: client.open_orders(wallet),
            )
            if isinstance(orders, list):
                stored = repo.store_open_orders(wallet, orders)
                wallet_open_orders += len(stored)
                result.open_orders_stored += len(stored)

        if plan.include_frontend_open_orders:
            frontend_orders = await _record_backfill_call(
                repo,
                run_id,
                plan,
                result,
                item_type="frontendOpenOrders",
                request_payload=build_frontend_open_orders_payload(wallet),
                wallet_address=wallet,
                call=lambda wallet=wallet: client.frontend_open_orders(wallet),
            )
            if isinstance(frontend_orders, list):
                stored = repo.store_open_orders(wallet, frontend_orders)
                wallet_open_orders += len(stored)
                result.open_orders_stored += len(stored)

        status = "SUCCESS" if result.errors_count == wallet_errors_before else "PARTIAL"
        if not unique_fills:
            status = "INCOMPLETE"
            result.notes.append("no_fills_collected")
        repo.finish_wallet_backfill_run(
            backfill_run,
            status=status,
            fills_count=len(unique_fills),
            open_orders_count=wallet_open_orders,
            deltas_count=len(rebuild.deltas),
            errors_count=result.errors_count - wallet_errors_before,
            confidence_score=rebuild.confidence_score,
            notes=";".join(sorted(set(rebuild.notes or result.notes))) or None,
        )


async def _collect_user_fills_by_time(
    client: HyperliquidInfoClient,
    repo: CollectionRepository,
    run_id: int,
    plan: WalletBackfillPlan,
    result: WalletBackfillResult,
    wallet: str,
    start_ms: int,
    end_ms: int,
    fills_for_rebuild: list[dict[str, Any]],
) -> None:
    page_index = 0
    started = now_ms()
    try:
        async for page in client.iter_user_fills_by_time(
            wallet,
            start_ms,
            end_ms,
            page_window_ms=plan.page_window_ms,
            max_pages=plan.limit_pages,
        ):
            page_index += 1
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
                    request_payload=build_user_fills_by_time_payload(wallet, start_ms, end_ms),
                    response_payload=page,
                    wallet_address=wallet,
                )
                result.raw_events_stored += 1
            result.fetched_items += 1
            fills_for_rebuild.extend(page)
            result.fills_stored += len(repo.store_fills(wallet, page))
    except Exception as exc:  # noqa: BLE001 - stored in DB as collection failure.
        error_message = str(exc)
        result.errors_count += 1
        repo.add_collection_item(
            run_id=run_id,
            item_type="userFillsByTime",
            wallet_address=wallet,
            status="error",
            error_message=error_message,
        )
        repo.store_api_health(
            service="hyperliquid_info:userFillsByTime",
            ok=False,
            latency_ms=now_ms() - started,
            error=error_message,
        )
        if plan.store_raw:
            repo.store_raw_event(
                source="hyperliquid",
                endpoint="/info",
                request_type="userFillsByTime",
                request_payload=build_user_fills_by_time_payload(wallet, start_ms, end_ms),
                response_payload={"error": error_message},
                wallet_address=wallet,
                success=False,
                error_message=error_message,
            )
            result.raw_events_stored += 1


async def _record_backfill_call(
    repo: CollectionRepository,
    run_id: int,
    plan: WalletBackfillPlan,
    result: WalletBackfillResult,
    *,
    item_type: str,
    request_payload: dict[str, Any],
    call: Callable[[], Any],
    wallet_address: str | None = None,
    coin: str | None = None,
) -> Any | None:
    started = now_ms()
    try:
        payload = await call()
    except Exception as exc:  # noqa: BLE001 - audit trail is stored before continuing.
        error_message = str(exc)
        result.errors_count += 1
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
        return None

    repo.add_collection_item(
        run_id=run_id,
        item_type=item_type,
        wallet_address=wallet_address,
        coin=coin,
        status="ok",
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
            response_payload=payload,
            wallet_address=wallet_address,
            coin=coin,
        )
        result.raw_events_stored += 1
    result.fetched_items += 1
    return payload


def _unique_fills(fills: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: set[str] = set()
    unique: list[dict[str, Any]] = []
    for fill in fills:
        fill_hash = stable_payload_hash(fill)
        if fill_hash in seen:
            continue
        seen.add(fill_hash)
        unique.append(fill)
    return unique


def _rolling_average(previous_average: float, new_value: float, count: int) -> float:
    if count <= 1:
        return new_value
    return ((previous_average * (count - 1)) + new_value) / count
