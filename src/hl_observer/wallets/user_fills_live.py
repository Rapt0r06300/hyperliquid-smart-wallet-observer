from __future__ import annotations

import asyncio
import json
from collections.abc import Iterable
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy.orm import Session

from hl_observer.collection.collector import WALLET_RE
from hl_observer.config.settings import Settings
from hl_observer.storage.repositories import CollectionRepository
from hl_observer.utils.time import now_ms
from hl_observer.wallets.position_delta_engine import build_position_delta_from_fill


@dataclass(slots=True)
class UserFillsLiveResult:
    wallets: list[str]
    duration_seconds: int
    network_read: bool = False
    messages_seen: int = 0
    fills_seen: int = 0
    snapshots_ignored: int = 0
    stale_fills_ignored: int = 0
    fills_stored: int = 0
    deltas_stored: int = 0
    stopped_reason: str = "not_started"
    warnings: list[str] = field(default_factory=list)
    wallet_fills: dict[str, list[dict[str, Any]]] = field(default_factory=dict)


def normalize_user_fill_wallets(wallets: Iterable[str], *, max_users: int = 10) -> list[str]:
    max_users = max(1, min(int(max_users), 10))
    normalized: list[str] = []
    seen: set[str] = set()
    for raw_wallet in wallets:
        wallet = str(raw_wallet or "").strip()
        if not WALLET_RE.fullmatch(wallet):
            continue
        key = wallet.lower()
        if key in seen:
            continue
        seen.add(key)
        normalized.append(key)
        if len(normalized) >= max_users:
            break
    return normalized


def user_fills_from_message(message: str | bytes | dict[str, Any]) -> tuple[str | None, bool, list[dict[str, Any]]]:
    if isinstance(message, bytes):
        message = message.decode("utf-8", errors="replace")
    payload: Any
    if isinstance(message, str):
        payload = json.loads(message)
    else:
        payload = message
    if not isinstance(payload, dict) or payload.get("channel") != "userFills":
        return None, False, []
    data = payload.get("data")
    if not isinstance(data, dict):
        return None, False, []
    wallet = data.get("user") or data.get("userAddress") or data.get("wallet") or payload.get("user")
    wallet = str(wallet).lower() if wallet and WALLET_RE.fullmatch(str(wallet)) else None
    is_snapshot = bool(data.get("isSnapshot") or payload.get("isSnapshot"))
    fills = data.get("fills")
    if not isinstance(fills, list):
        return wallet, is_snapshot, []
    return wallet, is_snapshot, [fill for fill in fills if isinstance(fill, dict)]


def _safe_int(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _strip_internal_fill_metadata(fill: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in fill.items() if not str(key).startswith("_hypersmart_")}


async def scan_user_fills_ws(
    settings: Settings,
    *,
    wallets: Iterable[str],
    duration_seconds: int = 30,
    max_users: int = 10,
    network_read: bool = False,
    ignore_snapshots: bool = True,
    websocket_connect: Any | None = None,
) -> UserFillsLiveResult:
    selected_wallets = normalize_user_fill_wallets(wallets, max_users=max_users)
    duration_seconds = max(1, min(int(duration_seconds), 300))
    result = UserFillsLiveResult(
        wallets=selected_wallets,
        duration_seconds=duration_seconds,
        network_read=network_read,
        stopped_reason="duration_elapsed",
    )
    if not network_read:
        result.stopped_reason = "NETWORK_READ_DISABLED"
        result.warnings.append("Network read disabled: userFills WebSocket not opened.")
        return result
    if not selected_wallets:
        result.stopped_reason = "SOURCE_UNAVAILABLE"
        result.warnings.append("No complete wallet addresses available for userFills WebSocket.")
        return result
    if websocket_connect is None:
        import websockets

        websocket_connect = websockets.connect

    deadline = asyncio.get_running_loop().time() + duration_seconds
    try:
        async with websocket_connect(settings.hyperliquid.ws_base_url) as ws:
            for wallet in selected_wallets:
                await ws.send(
                    json.dumps(
                        {
                            "method": "subscribe",
                            "subscription": {
                                "type": "userFills",
                                "user": wallet,
                                "aggregateByTime": False,
                            },
                        }
                    )
                )
            async for message in _bounded_ws_messages(ws, deadline):
                result.messages_seen += 1
                wallet, is_snapshot, fills = user_fills_from_message(message)
                if is_snapshot and ignore_snapshots:
                    result.snapshots_ignored += len(fills)
                    continue
                if not wallet or wallet not in selected_wallets:
                    continue
                if not fills:
                    continue
                received_at_ms = now_ms()
                enriched_fills: list[dict[str, Any]] = []
                for fill in fills:
                    enriched = dict(fill)
                    enriched["_hypersmart_source"] = "hyperliquid_ws:userFills"
                    enriched["_hypersmart_ws_received_at_ms"] = received_at_ms
                    enriched["_hypersmart_ws_is_snapshot"] = False
                    enriched_fills.append(enriched)
                result.fills_seen += len(enriched_fills)
                result.wallet_fills.setdefault(wallet, []).extend(enriched_fills)
    except TimeoutError:
        result.stopped_reason = "duration_elapsed"
    except Exception as exc:  # noqa: BLE001 - the CLI reports the source failure instead of crashing.
        result.stopped_reason = "SOURCE_UNAVAILABLE"
        result.warnings.append(f"userFills WebSocket unavailable: {exc}")
    return result


async def _bounded_ws_messages(ws: Any, deadline: float):
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


def store_user_fills_live_result(
    session: Session,
    result: UserFillsLiveResult,
    *,
    max_live_fill_age_ms: int = 20_000,
) -> UserFillsLiveResult:
    result.stale_fills_ignored = 0
    result.fills_stored = 0
    result.deltas_stored = 0
    repo = CollectionRepository(session)
    latest_event_ms = 0
    for wallet, fills in result.wallet_fills.items():
        fresh_fills: list[dict[str, Any]] = []
        for fill in fills:
            fill_time_ms = _safe_int(fill.get("time") or fill.get("timestamp"))
            received_at_ms = _safe_int(fill.get("_hypersmart_ws_received_at_ms")) or now_ms()
            if (
                max_live_fill_age_ms > 0
                and fill_time_ms is not None
                and received_at_ms - fill_time_ms > max_live_fill_age_ms
            ):
                result.stale_fills_ignored += 1
                continue
            fresh_fills.append(fill)

        public_fills = [_strip_internal_fill_metadata(fill) for fill in fresh_fills]
        stored = repo.store_fills(wallet, public_fills)
        result.fills_stored += len(stored)
        deltas = []
        for fill in fresh_fills:
            try:
                deltas.append(build_position_delta_from_fill(wallet, fill))
                latest_event_ms = max(latest_event_ms, int(fill.get("time") or fill.get("timestamp") or 0))
            except Exception as exc:  # noqa: BLE001 - malformed fills are recorded as warnings.
                result.warnings.append(f"fill skipped for {wallet}: {exc}")
        result.deltas_stored += len(repo.store_position_deltas(deltas))
    repo.update_source_health(
        "hyperliquid_ws:userFills",
        is_success=result.stopped_reason != "SOURCE_UNAVAILABLE",
        is_heartbeat=True,
        event_timestamp_ms=latest_event_ms or now_ms(),
        error_message="; ".join(result.warnings) if result.warnings else None,
    )
    return result


def format_user_fills_live_report(result: UserFillsLiveResult) -> str:
    lines = [
        "userFills live shortlist scan report",
        "source: hyperliquid_ws:userFills",
        f"wallets_subscribed: {len(result.wallets)}/10",
        f"duration_seconds: {result.duration_seconds}",
        f"network_read: {result.network_read}",
        f"messages_seen: {result.messages_seen}",
        f"fills_seen: {result.fills_seen}",
        f"snapshots_ignored: {result.snapshots_ignored}",
        f"stale_fills_ignored: {result.stale_fills_ignored}",
        f"fills_stored: {result.fills_stored}",
        f"deltas_stored: {result.deltas_stored}",
        f"stopped_reason: {result.stopped_reason}",
        "mode: read-only shortlist userFills only; no exchange, no signature, no order",
    ]
    if result.warnings:
        lines.append(f"warnings: {'; '.join(result.warnings)}")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# V16 — PERSISTENT real-time userFills stream (fast data, FREE, sub-second).
# The 15s polled snapshot scan above leaves entries ~10s stale (the edge lives
# in ~4s). This stays connected and stores each FRESH (post-connect, non-snapshot)
# fill the instant it arrives, with reconnect/backoff. HL caps userFills at 10
# wallets, so this watches the 10 highest-priority (best) leaders — fast data +
# leader quality at once. read-only / paper-only: never an order or signature.
# ---------------------------------------------------------------------------

@dataclass(slots=True)
class StreamStats:
    connects: int = 0
    reconnects: int = 0
    messages_seen: int = 0
    fresh_fills_stored: int = 0
    deltas_stored: int = 0
    snapshots_ignored: int = 0
    last_fill_age_ms: int | None = None
    stopped_reason: str = "not_started"
    warnings: list[str] = field(default_factory=list)


def _store_fresh_fills(session_factory: Any, wallet: str, fills: list[dict[str, Any]],
                       *, max_live_fill_age_ms: int, stats: StreamStats) -> None:
    """Store one fresh batch immediately (short session) so copy-run sees it now."""
    res = UserFillsLiveResult(wallets=[wallet], duration_seconds=1, network_read=True,
                              stopped_reason="stream_batch")
    res.wallet_fills[wallet] = fills
    with session_factory() as session:
        store_user_fills_live_result(session, res, max_live_fill_age_ms=max_live_fill_age_ms)
        session.commit()
    stats.fresh_fills_stored += res.fills_stored
    stats.deltas_stored += res.deltas_stored
    stats.snapshots_ignored += res.snapshots_ignored


async def stream_user_fills_ws(
    settings: Settings,
    *,
    wallets: Iterable[str],
    session_factory: Any,
    max_users: int = 10,
    network_read: bool = False,
    websocket_connect: Any | None = None,
    stop_event: Any | None = None,
    max_live_fill_age_ms: int = 20_000,
    max_reconnects: int | None = None,
    backoff_schedule_s: tuple[int, ...] = (1, 2, 5, 10, 30),
    sleep: Any | None = None,
) -> StreamStats:
    """Persistent userFills consumer. Stays connected and stores fresh deltas as they
    arrive (sub-second). Reconnects with bounded backoff. Stops on stop_event or after
    max_reconnects (tests). Pure transport only — no order, no signature."""
    stats = StreamStats(stopped_reason="duration_elapsed")
    selected = normalize_user_fill_wallets(wallets, max_users=max_users)
    if not network_read:
        stats.stopped_reason = "NETWORK_READ_DISABLED"
        stats.warnings.append("Network read disabled: persistent userFills stream not opened.")
        return stats
    if not selected:
        stats.stopped_reason = "SOURCE_UNAVAILABLE"
        stats.warnings.append("No complete wallet addresses for persistent userFills stream.")
        return stats
    if websocket_connect is None:
        import websockets
        websocket_connect = websockets.connect
    if sleep is None:
        sleep = asyncio.sleep

    def _stopped() -> bool:
        return bool(stop_event is not None and getattr(stop_event, "is_set", lambda: False)())

    attempt = 0
    while not _stopped():
        try:
            async with websocket_connect(settings.hyperliquid.ws_base_url) as ws:
                stats.connects += 1
                attempt = 0  # reset backoff on a clean connect
                for wallet in selected:
                    await ws.send(json.dumps({
                        "method": "subscribe",
                        "subscription": {"type": "userFills", "user": wallet, "aggregateByTime": False},
                    }))
                while not _stopped():
                    try:
                        message = await asyncio.wait_for(ws.recv(), timeout=30.0)
                    except TimeoutError:
                        continue                       # idle; keep the socket alive
                    stats.messages_seen += 1
                    wallet, is_snapshot, fills = user_fills_from_message(message)
                    if is_snapshot:
                        stats.snapshots_ignored += len(fills)   # historical -> ignore (we want FRESH)
                        continue
                    if not wallet or wallet not in selected or not fills:
                        continue
                    received = now_ms()
                    enriched = []
                    for fill in fills:
                        e = dict(fill)
                        e["_hypersmart_source"] = "hyperliquid_ws:userFills:stream"
                        e["_hypersmart_ws_received_at_ms"] = received
                        e["_hypersmart_ws_is_snapshot"] = False
                        enriched.append(e)
                        ft = _safe_int(fill.get("time") or fill.get("timestamp"))
                        if ft is not None:
                            stats.last_fill_age_ms = max(0, received - ft)
                    try:
                        _store_fresh_fills(session_factory, wallet, enriched,
                                           max_live_fill_age_ms=max_live_fill_age_ms, stats=stats)
                    except Exception as exc:  # noqa: BLE001
                        stats.warnings.append(f"store failed: {exc}")
        except Exception as exc:  # noqa: BLE001 - reconnect on any transport error
            stats.warnings.append(f"ws error: {exc}")
        if _stopped():
            stats.stopped_reason = "stopped"
            break
        stats.reconnects += 1
        if max_reconnects is not None and stats.reconnects > max_reconnects:
            stats.stopped_reason = "max_reconnects"
            break
        idx = min(attempt, len(backoff_schedule_s) - 1)
        attempt += 1
        await sleep(backoff_schedule_s[idx])
    return stats


__all__ = [
    "UserFillsLiveResult", "normalize_user_fill_wallets", "user_fills_from_message",
    "scan_user_fills_ws", "store_user_fills_live_result", "format_user_fills_live_report",
    "StreamStats", "stream_user_fills_ws",
]
