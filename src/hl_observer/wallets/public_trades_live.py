from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator, Iterable
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy.orm import Session

from hl_observer.collection.collector import WALLET_RE
from hl_observer.config.settings import Settings
from hl_observer.storage.models import (
    RawEvent,
    TopWallet,
    WalletCandidateModel,
    WalletDiscoveryRun,
)
from hl_observer.storage.repositories import CollectionRepository, stable_payload_hash
from hl_observer.utils.time import now_ms

DEFAULT_PUBLIC_TRADE_COINS = ["BTC", "ETH", "SOL", "HYPE", "DOGE", "XRP", "BNB", "ENA", "AVAX", "LINK"]


@dataclass(slots=True)
class PublicTradeWalletStats:
    wallet_address: str
    trades_count: int = 0
    observed_notional_usdc: float = 0.0
    coins: set[str] = field(default_factory=set)
    first_seen_ms: int | None = None
    last_seen_ms: int | None = None
    sample_trades: list[dict[str, Any]] = field(default_factory=list)

    @property
    def score(self) -> float:
        activity_score = min(45.0, self.trades_count * 3.0)
        notional_score = min(45.0, self.observed_notional_usdc / 10_000.0)
        breadth_score = min(10.0, len(self.coins) * 2.0)
        return round(activity_score + notional_score + breadth_score, 6)


@dataclass(slots=True)
class PublicTradeScanResult:
    coins: list[str]
    duration_seconds: int
    messages_seen: int = 0
    trades_seen: int = 0
    wallets_seen: int = 0
    wallets_stored: int = 0
    raw_events_stored: int = 0
    source: str = "hyperliquid_ws_public_trades"
    network_read: bool = False
    stopped_reason: str = "not_started"
    warnings: list[str] = field(default_factory=list)
    wallet_stats: dict[str, PublicTradeWalletStats] = field(default_factory=dict)
    raw_trade_samples: list[dict[str, Any]] = field(default_factory=list)


def normalize_coin_list(coins: str | Iterable[str] | None) -> list[str]:
    if coins is None:
        return list(DEFAULT_PUBLIC_TRADE_COINS)
    if isinstance(coins, str):
        items = [item.strip() for item in coins.split(",")]
    else:
        items = [str(item).strip() for item in coins]
    normalized: list[str] = []
    seen: set[str] = set()
    for item in items:
        if not item:
            continue
        coin = item.upper()
        if coin in seen:
            continue
        seen.add(coin)
        normalized.append(coin)
    return normalized or list(DEFAULT_PUBLIC_TRADE_COINS)


def trade_payloads_from_message(message: str | bytes | dict[str, Any]) -> list[dict[str, Any]]:
    if isinstance(message, bytes):
        message = message.decode("utf-8", errors="replace")
    payload: Any
    if isinstance(message, str):
        payload = json.loads(message)
    else:
        payload = message
    if not isinstance(payload, dict):
        return []
    if payload.get("channel") != "trades":
        return []
    data = payload.get("data")
    if isinstance(data, list):
        return [item for item in data if isinstance(item, dict)]
    if isinstance(data, dict):
        trades = data.get("trades")
        if isinstance(trades, list):
            return [item for item in trades if isinstance(item, dict)]
    return []


def ingest_public_trade_messages(
    messages: Iterable[str | bytes | dict[str, Any]],
    *,
    coins: list[str] | None = None,
    max_wallets: int = 500,
    min_notional_usdc: float = 0.0,
    sample_limit: int = 200,
) -> PublicTradeScanResult:
    selected_coins = normalize_coin_list(coins)
    selected_set = set(selected_coins)
    result = PublicTradeScanResult(
        coins=selected_coins,
        duration_seconds=0,
        network_read=False,
        stopped_reason="messages_exhausted",
    )
    for message in messages:
        result.messages_seen += 1
        for trade in trade_payloads_from_message(message):
            coin = str(trade.get("coin") or "").upper()
            if selected_set and coin not in selected_set:
                continue
            result.trades_seen += 1
            _ingest_trade(result, trade, max_wallets=max_wallets, min_notional_usdc=min_notional_usdc)
            if len(result.raw_trade_samples) < sample_limit:
                result.raw_trade_samples.append(trade)
    result.wallets_seen = len(result.wallet_stats)
    return result


async def scan_public_trades_ws(
    settings: Settings,
    *,
    coins: list[str] | None = None,
    duration_seconds: int = 45,
    max_wallets: int = 500,
    min_notional_usdc: float = 0.0,
    network_read: bool = False,
    websocket_connect: Any | None = None,
) -> PublicTradeScanResult:
    selected_coins = normalize_coin_list(coins)
    duration_seconds = max(1, min(int(duration_seconds), 300))
    result = PublicTradeScanResult(
        coins=selected_coins,
        duration_seconds=duration_seconds,
        network_read=network_read,
        stopped_reason="duration_elapsed",
    )
    if not network_read:
        result.stopped_reason = "NETWORK_READ_DISABLED"
        result.warnings.append("Network read disabled: public trades WebSocket not opened.")
        return result

    if websocket_connect is None:
        import websockets

        websocket_connect = websockets.connect

    url = settings.hyperliquid.ws_base_url
    deadline = asyncio.get_running_loop().time() + duration_seconds
    try:
        async with websocket_connect(url) as ws:
            for coin in selected_coins:
                await ws.send(json.dumps({"method": "subscribe", "subscription": {"type": "trades", "coin": coin}}))
            async for message in _bounded_ws_messages(ws, deadline):
                result.messages_seen += 1
                for trade in trade_payloads_from_message(message):
                    result.trades_seen += 1
                    _ingest_trade(result, trade, max_wallets=max_wallets, min_notional_usdc=min_notional_usdc)
                    if len(result.raw_trade_samples) < 200:
                        result.raw_trade_samples.append(trade)
    except TimeoutError:
        result.stopped_reason = "duration_elapsed"
    except Exception as exc:  # noqa: BLE001 - CLI reports source health instead of crashing the UI loop.
        result.stopped_reason = "SOURCE_UNAVAILABLE"
        result.warnings.append(f"Public trades WebSocket unavailable: {exc}")
    result.wallets_seen = len(result.wallet_stats)
    return result


async def _bounded_ws_messages(ws: Any, deadline: float) -> AsyncIterator[str | bytes]:
    while True:
        remaining = deadline - asyncio.get_running_loop().time()
        if remaining <= 0:
            return
        try:
            message = await asyncio.wait_for(ws.recv(), timeout=min(remaining, 5.0))
        except TimeoutError:
            if asyncio.get_running_loop().time() >= deadline:
                return
            continue
        yield message


def _ingest_trade(
    result: PublicTradeScanResult,
    trade: dict[str, Any],
    *,
    max_wallets: int,
    min_notional_usdc: float,
) -> None:
    coin = str(trade.get("coin") or "").upper()
    price = _safe_float(trade.get("px"))
    size = _safe_float(trade.get("sz"))
    notional = abs((price or 0.0) * (size or 0.0))
    if notional < max(0.0, min_notional_usdc):
        return
    trade_time = _safe_int(trade.get("time")) or now_ms()
    users = trade.get("users")
    if not isinstance(users, list):
        return
    for raw_user in users:
        wallet = str(raw_user)
        if not WALLET_RE.fullmatch(wallet):
            continue
        key = wallet.lower()
        if key not in result.wallet_stats and len(result.wallet_stats) >= max(1, max_wallets):
            continue
        stats = result.wallet_stats.setdefault(key, PublicTradeWalletStats(wallet_address=wallet))
        stats.trades_count += 1
        stats.observed_notional_usdc += notional
        if coin:
            stats.coins.add(coin)
        stats.first_seen_ms = trade_time if stats.first_seen_ms is None else min(stats.first_seen_ms, trade_time)
        stats.last_seen_ms = trade_time if stats.last_seen_ms is None else max(stats.last_seen_ms, trade_time)
        if len(stats.sample_trades) < 5:
            stats.sample_trades.append(trade)


def store_public_trade_scan(
    session: Session,
    result: PublicTradeScanResult,
    *,
    promote_top: int = 50,
) -> PublicTradeScanResult:
    repo = CollectionRepository(session)

    # Calculate latest event time from result.wallet_stats
    last_event_ms = 0
    for stats in result.wallet_stats.values():
        if stats.last_seen_ms:
            last_event_ms = max(last_event_ms, stats.last_seen_ms)

    repo.update_source_health(
        result.source,
        is_success=result.stopped_reason != "SOURCE_UNAVAILABLE",
        is_heartbeat=True,
        event_timestamp_ms=last_event_ms if last_event_ms > 0 else None,
        error_message="; ".join(result.warnings) if result.warnings else None,
    )

    run = WalletDiscoveryRun(
        started_at_ms=now_ms(),
        finished_at_ms=now_ms(),
        status="COMPLETED" if result.stopped_reason != "SOURCE_UNAVAILABLE" else "PARTIAL",
        sources_attempted=1,
        candidates_found=len(result.wallet_stats),
        candidates_after_filter=len(result.wallet_stats),
        wallets_selected=min(len(result.wallet_stats), max(0, promote_top)),
        errors_count=1 if result.stopped_reason == "SOURCE_UNAVAILABLE" else 0,
        notes=f"public_trades_ws;stopped_reason={result.stopped_reason}",
    )
    session.add(run)
    session.flush()
    if result.raw_trade_samples:
        payload_hash = stable_payload_hash(result.raw_trade_samples)
        session.add(
            RawEvent(
                source=result.source,
                endpoint="wss://api.hyperliquid.xyz/ws",
                request_type="trades",
                wallet_address=None,
                coin=",".join(result.coins),
                request_payload_json={"subscriptions": [{"type": "trades", "coin": coin} for coin in result.coins]},
                response_payload_json=result.raw_trade_samples,
                response_hash=payload_hash,
                fetched_at_ms=now_ms(),
                success=result.stopped_reason != "SOURCE_UNAVAILABLE",
                error_message="; ".join(result.warnings) if result.warnings else None,
                event_type="public_trades_ws",
                wallet=None,
                exchange_ts=None,
                local_received_ts=now_ms(),
                payload_json={"trades": result.raw_trade_samples},
                payload_hash=payload_hash,
            )
        )
        result.raw_events_stored += 1

    ranked = sorted(result.wallet_stats.values(), key=lambda item: item.score, reverse=True)
    for index, stats in enumerate(ranked, start=1):
        confidence = min(95.0, 35.0 + stats.score)
        session.add(
            WalletCandidateModel(
                run_id=run.id,
                address=stats.wallet_address,
                coin=",".join(sorted(stats.coins))[:32] or None,
                source_name="public_trades_ws",
                source_type="websocket_read_only",
                label="fresh_public_trade_wallet",
                external_pnl_usdc=None,
                external_roi_pct=None,
                external_volume_usdc=round(stats.observed_notional_usdc, 6),
                external_win_rate=None,
                external_position_usdc=None,
                external_unrealized_pnl=None,
                external_funding_fee=None,
                first_seen_ms=stats.first_seen_ms or now_ms(),
                last_seen_ms=stats.last_seen_ms or now_ms(),
                raw_payload_json={
                    "trades_count": stats.trades_count,
                    "coins": sorted(stats.coins),
                    "sample_trades": stats.sample_trades,
                    "research_only": True,
                    "warning": "public trades identify active wallets but do not prove open/close direction",
                },
                confidence_score=confidence,
                selected_for_backfill=index <= promote_top,
                rejection_reason=None if index <= promote_top else "OUTSIDE_PROMOTION_LIMIT",
            )
        )
        if index <= promote_top:
            session.add(
                TopWallet(
                    wallet_address=stats.wallet_address,
                    rank=index,
                    source="public_trades_ws",
                    score=stats.score,
                    selected_at_ms=now_ms(),
                    status="selected",
                    notes=(
                        "fresh_public_trades_ws;read_only;requires_/info_confirmation;"
                        "not_a_trading_signal"
                    ),
                )
            )
            result.wallets_stored += 1
    return result


def format_public_trade_scan_report(result: PublicTradeScanResult) -> str:
    lines = [
        "public-trades live scan report",
        f"source: {result.source}",
        f"coins: {', '.join(result.coins)}",
        f"duration_seconds: {result.duration_seconds}",
        f"network_read: {result.network_read}",
        f"messages_seen: {result.messages_seen}",
        f"trades_seen: {result.trades_seen}",
        f"wallets_seen: {len(result.wallet_stats)}",
        f"wallets_promoted_for_followup: {result.wallets_stored}",
        f"raw_events_stored: {result.raw_events_stored}",
        f"stopped_reason: {result.stopped_reason}",
        "mode: read-only discovery only; public trades are not enough to infer open/close",
    ]
    if result.warnings:
        lines.append(f"warnings: {'; '.join(result.warnings)}")
    top = sorted(result.wallet_stats.values(), key=lambda item: item.score, reverse=True)[:10]
    for stats in top:
        lines.append(
            f"- {stats.wallet_address} trades={stats.trades_count} "
            f"notional=${stats.observed_notional_usdc:.2f} coins={','.join(sorted(stats.coins))} "
            f"score={stats.score:.1f}"
        )
    return "\n".join(lines)


def _safe_float(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _safe_int(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None
