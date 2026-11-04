from __future__ import annotations

import asyncio
import json
import random
from collections.abc import Iterable
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy.orm import Session

from hl_observer.collection.collector import WALLET_RE
from hl_observer.config.settings import Settings
from hl_observer.ops.echec_silencieux import noter as _noter_echec
from hl_observer.storage.repositories import CollectionRepository
from hl_observer.utils.time import now_ms
from hl_observer.wallets.position_delta_engine import build_position_delta_from_fill


def _decode_ws_message(message: str | bytes | dict[str, Any]) -> dict[str, Any] | None:
    if isinstance(message, bytes):
        message = message.decode("utf-8", errors="replace")
    if isinstance(message, str):
        try:
            message = json.loads(message)
        except (TypeError, ValueError, json.JSONDecodeError):
            return None
    return message if isinstance(message, dict) else None


def user_fills_subscription_ack(message: str | bytes | dict[str, Any]) -> str | None:
    """Return the wallet acknowledged by a real userFills subscribe response."""
    payload = _decode_ws_message(message)
    if not payload or payload.get("channel") != "subscriptionResponse":
        return None
    data = payload.get("data")
    subscription = data.get("subscription") if isinstance(data, dict) else None
    if (
        not isinstance(data, dict)
        or data.get("method") != "subscribe"
        or not isinstance(subscription, dict)
        or subscription.get("type") != "userFills"
    ):
        return None
    wallet = subscription.get("user")
    return str(wallet).lower() if wallet and WALLET_RE.fullmatch(str(wallet)) else None


def _native_fill_identity(fill: dict[str, Any]) -> dict[str, Any]:
    """Copy only venue-provided identity fields; never synthesize an event id."""
    return {
        key: fill[key]
        for key in ("hash", "tid", "oid")
        if fill.get(key) is not None and str(fill[key]).strip()
    }


def _live_fill_provenance(fill: dict[str, Any]) -> dict[str, Any] | None:
    source = str(fill.get("_hypersmart_source") or "")
    received_at = _safe_positive_int(fill.get("_hypersmart_ws_received_at_ms"))
    ack_at = _safe_positive_int(fill.get("_hypersmart_ws_ack_received_at_ms"))
    connection_id = str(fill.get("_hypersmart_ws_connection_id") or "").strip()
    if (
        source not in {"hyperliquid_ws:userFills", "hyperliquid_ws:userFills:stream"}
        or received_at is None
        or ack_at is None
        or not connection_id
        or fill.get("_hypersmart_ws_is_snapshot") is not False
    ):
        return None
    provenance: dict[str, Any] = {
        "channel": "userFills",
        "source": source,
        "received_at_ms": received_at,
        "ack_received_at_ms": ack_at,
        "connection_id": connection_id,
        "is_snapshot": False,
        "native_identity": _native_fill_identity(fill),
    }
    sequence = fill.get("_hypersmart_ws_frame_sequence")
    if type(sequence) is int and sequence >= 0:
        provenance["frame_sequence"] = sequence
    return provenance


@dataclass(slots=True)
class UserFillsLiveResult:
    wallets: list[str]
    duration_seconds: int
    network_read: bool = False
    messages_seen: int = 0
    fills_seen: int = 0
    snapshots_ignored: int = 0
    unclassified_fills_ignored: int = 0
    unacked_fills_ignored: int = 0
    subscription_acks_seen: int = 0
    stale_fills_ignored: int = 0
    fills_stored: int = 0
    deltas_stored: int = 0
    fills_quarantined: int = 0
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


def user_fills_from_message(message: str | bytes | dict[str, Any]) -> tuple[str | None, bool | None, list[dict[str, Any]]]:
    payload: Any = _decode_ws_message(message)
    if not isinstance(payload, dict) or payload.get("channel") != "userFills":
        return None, False, []
    data = payload.get("data")
    if not isinstance(data, dict):
        return None, False, []
    wallet = data.get("user") or data.get("userAddress") or data.get("wallet") or payload.get("user")
    wallet = str(wallet).lower() if wallet and WALLET_RE.fullmatch(str(wallet)) else None
    raw_snapshot = data["isSnapshot"] if "isSnapshot" in data else payload.get("isSnapshot")
    is_snapshot = raw_snapshot if type(raw_snapshot) is bool else None
    fills = data.get("fills")
    if not isinstance(fills, list):
        return wallet, is_snapshot, []
    return wallet, is_snapshot, [fill for fill in fills if isinstance(fill, dict)]


def _safe_positive_int(value: Any) -> int | None:
    """Parse an exact positive millisecond value without truncation or coercion."""

    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, int):
        return value if value > 0 else None
    if isinstance(value, str) and value.strip().isdecimal():
        try:
            parsed = int(value.strip())
        except (TypeError, ValueError, OverflowError):
            return None
        return parsed if parsed > 0 else None
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
    acknowledged_wallets: set[str] = set()
    ack_received_at_ms: dict[str, int] = {}
    connection_id = f"scan-{id(result):x}"
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
                ack_wallet = user_fills_subscription_ack(message)
                if ack_wallet is not None:
                    if ack_wallet in selected_wallets:
                        acknowledged_wallets.add(ack_wallet)
                        ack_received_at_ms[ack_wallet] = now_ms()
                        result.subscription_acks_seen += 1
                    continue
                wallet, is_snapshot, fills = user_fills_from_message(message)
                if is_snapshot is None:
                    # Missing or malformed classification is not proof of a live
                    # event, even when a caller explicitly asks to retain snapshots.
                    result.unclassified_fills_ignored += len(fills)
                    continue
                if is_snapshot is True and ignore_snapshots:
                    result.snapshots_ignored += len(fills)
                    continue
                if not wallet or wallet not in selected_wallets:
                    continue
                if not fills:
                    continue
                if wallet not in acknowledged_wallets:
                    result.unacked_fills_ignored += len(fills)
                    result.warnings.append(
                        f"fill quarantined for {wallet}: subscription ACK not observed"
                    )
                    continue
                received_at_ms = now_ms()
                enriched_fills: list[dict[str, Any]] = []
                for fill in fills:
                    enriched = dict(fill)
                    enriched["_hypersmart_source"] = "hyperliquid_ws:userFills"
                    enriched["_hypersmart_ws_received_at_ms"] = received_at_ms
                    enriched["_hypersmart_ws_is_snapshot"] = False
                    enriched["_hypersmart_ws_ack_received_at_ms"] = ack_received_at_ms[wallet]
                    enriched["_hypersmart_ws_connection_id"] = connection_id
                    enriched_fills.append(enriched)
                result.fills_seen += len(enriched_fills)
                result.wallet_fills.setdefault(wallet, []).extend(enriched_fills)
    except TimeoutError:
        result.stopped_reason = "duration_elapsed"
    except Exception as exc:  # noqa: BLE001 - the CLI reports the source failure instead of crashing.
        result.stopped_reason = "SOURCE_UNAVAILABLE"
        result.warnings.append(f"userFills WebSocket unavailable: {exc}")
    missing_ack_wallets = sorted(set(selected_wallets) - acknowledged_wallets)
    if missing_ack_wallets:
        result.warnings.append(
            "subscription ACK incomplete; wallets quarantined: " + ", ".join(missing_ack_wallets)
        )
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
    result.fills_quarantined = 0
    repo = CollectionRepository(session)
    latest_event_ms = 0
    for wallet, fills in result.wallet_fills.items():
        fresh_fills: list[dict[str, Any]] = []
        for fill in fills:
            fill_time_ms = _safe_positive_int(fill.get("time") or fill.get("timestamp"))
            received_at_ms = _safe_positive_int(fill.get("_hypersmart_ws_received_at_ms"))
            if received_at_ms is None or received_at_ms <= 0:
                result.warnings.append(
                    f"fill quarantined for {wallet}: missing or invalid WebSocket receive timestamp"
                )
                continue
            if fill_time_ms is None or received_at_ms < fill_time_ms:
                result.warnings.append(
                    f"fill quarantined for {wallet}: invalid source/receive timestamp chronology"
                )
                continue
            if (
                max_live_fill_age_ms > 0
                and fill_time_ms is not None
                and received_at_ms - fill_time_ms > max_live_fill_age_ms
            ):
                result.stale_fills_ignored += 1
                continue
            fresh_fills.append(fill)

        valid_pairs: list[tuple[dict[str, Any], Any]] = []
        for fill in fresh_fills:
            try:
                delta = build_position_delta_from_fill(wallet, fill)
                latest_event_ms = max(latest_event_ms, int(fill.get("time") or fill.get("timestamp") or 0))
            except Exception as exc:  # noqa: BLE001 - malformed fills are recorded as warnings.
                result.fills_quarantined += 1
                result.warnings.append(f"fill skipped for {wallet}: {exc}")
                continue
            valid_pairs.append((fill, delta))

        if valid_pairs:
            try:
                # The nested transaction keeps a fill and its derived delta atomic
                # when a storage failure occurs after validation.
                with session.begin_nested():
                    public_fills: list[dict[str, Any]] = []
                    for fill, _ in valid_pairs:
                        public_fill = _strip_internal_fill_metadata(fill)
                        provenance = _live_fill_provenance(fill)
                        if provenance is not None:
                            public_fill["observer_provenance"] = provenance
                        public_fills.append(public_fill)
                    stored = repo.store_fills(wallet, public_fills)
                    stored_deltas = repo.store_position_deltas([delta for _, delta in valid_pairs])
                result.fills_stored += len(stored)
                result.deltas_stored += len(stored_deltas)
            except Exception as exc:  # noqa: BLE001 - quarantine the complete batch on storage failure.
                result.fills_quarantined += len(valid_pairs)
                result.warnings.append(f"fill batch quarantined for {wallet}: storage failed: {exc}")

    invalid_observations = (
        result.unclassified_fills_ignored
        + result.stale_fills_ignored
        + result.unacked_fills_ignored
        + result.fills_quarantined
    )
    data_consistent = invalid_observations == 0
    source_success = result.stopped_reason != "SOURCE_UNAVAILABLE" and data_consistent
    repo.update_source_health(
        "hyperliquid_ws:userFills",
        is_success=source_success,
        is_consistent=data_consistent,
        is_heartbeat=True,
        event_timestamp_ms=latest_event_ms or (now_ms() if source_success else None),
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
        f"unclassified_fills_ignored: {result.unclassified_fills_ignored}",
        f"unacked_fills_ignored: {result.unacked_fills_ignored}",
        f"subscription_acks_seen: {result.subscription_acks_seen}",
        f"stale_fills_ignored: {result.stale_fills_ignored}",
        f"fills_quarantined: {result.fills_quarantined}",
        f"fills_stored: {result.fills_stored}",
        f"deltas_stored: {result.deltas_stored}",
        f"stopped_reason: {result.stopped_reason}",
        "mode: read-only shortlist userFills only; no exchange, no signature, no order",
    ]
    if result.warnings:
        lines.append(f"warnings: {'; '.join(result.warnings)}")
    return "\n".join(lines)


def classify_snapshot_fill_entry(*, is_snapshot: Any, fill_count: int = 1) -> dict[str, Any]:
    """Classify a userFills payload without allowing a snapshot to open exposure."""

    if type(is_snapshot) is not bool or type(fill_count) is not int or fill_count < 0:
        return {"status": "UNMEASURABLE", "accept_new_entry": False,
                "reason": "SNAPSHOT_CLASSIFICATION_INVALID", "paper_read_only": True}
    if is_snapshot:
        return {"status": "PROVEN", "accept_new_entry": False,
                "reason": "SNAPSHOT_STATE_ONLY", "paper_read_only": True}
    return {"status": "PROVEN", "accept_new_entry": fill_count > 0,
            "reason": "LIVE_EVENT" if fill_count else "LIVE_EVENT_EMPTY",
            "paper_read_only": True}


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
    unclassified_fills_ignored: int = 0
    unacked_fills_ignored: int = 0
    subscription_acks_seen: int = 0
    connections_without_complete_ack: int = 0
    storage_failures: int = 0
    last_fill_age_ms: int | None = None
    stopped_reason: str = "not_started"
    warnings: list[str] = field(default_factory=list)


async def _store_fresh_fills(session_factory: Any, wallet: str, fills: list[dict[str, Any]],
                             *, max_live_fill_age_ms: int, stats: StreamStats,
                             sleep: Any, max_store_retries: int = 2) -> bool:
    """Store one fresh batch immediately (short session) so copy-run sees it now."""
    res = UserFillsLiveResult(wallets=[wallet], duration_seconds=1, network_read=True,
                              stopped_reason="stream_batch")
    res.wallet_fills[wallet] = fills
    for attempt in range(max(0, int(max_store_retries)) + 1):
        try:
            with session_factory() as session:
                store_user_fills_live_result(session, res, max_live_fill_age_ms=max_live_fill_age_ms)
                session.commit()
            stats.fresh_fills_stored += res.fills_stored
            stats.deltas_stored += res.deltas_stored
            stats.snapshots_ignored += res.snapshots_ignored
            return True
        except Exception as exc:  # noqa: BLE001 - retain the batch until bounded retries are exhausted.
            if attempt >= max_store_retries:
                stats.storage_failures += 1
                stats.warnings.append(f"store failed after {attempt + 1} attempts: {exc}")
                return False
            await sleep(min(1.0, 0.25 * (2 ** attempt)))
    return False


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
    connect_timeout_s: float = 15.0,
    recv_timeout_s: float = 30.0,
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
        connected_at = asyncio.get_running_loop().time()
        try:
            # Timeout DUR sur l'ouverture: un DNS/TCP qui pend ne doit JAMAIS geler le stream
            # (le stop_event est inconsultable pendant un connect bloquant). Vu en session
            # 2026-07-07: stream figé dès 21:03, jamais sorti de son segment de 300s.
            cm = websocket_connect(settings.hyperliquid.ws_base_url)
            ws = await asyncio.wait_for(cm.__aenter__(), timeout=max(1.0, float(connect_timeout_s)))
            try:
                stats.connects += 1
                connection_id = f"stream-{stats.connects}"
                acknowledged_wallets: set[str] = set()
                ack_received_at_ms: dict[str, int] = {}
                for wallet in selected:
                    await ws.send(json.dumps({
                        "method": "subscribe",
                        "subscription": {"type": "userFills", "user": wallet, "aggregateByTime": False},
                    }))
                while not _stopped():
                    try:
                        message = await asyncio.wait_for(ws.recv(), timeout=max(0.001, float(recv_timeout_s)))
                    except (TimeoutError, asyncio.TimeoutError):
                        # idle; keep the socket alive. Compat 3.10: asyncio.TimeoutError
                        # n'est PAS TimeoutError avant 3.11 -> sans ce double except, chaque
                        # période calme de 30s forçait une reconnexion complète.
                        continue
                    stats.messages_seen += 1
                    ack_wallet = user_fills_subscription_ack(message)
                    if ack_wallet is not None:
                        if ack_wallet in selected:
                            acknowledged_wallets.add(ack_wallet)
                            ack_received_at_ms[ack_wallet] = now_ms()
                            stats.subscription_acks_seen += 1
                        continue
                    wallet, is_snapshot, fills = user_fills_from_message(message)
                    if is_snapshot is None:
                        stats.unclassified_fills_ignored += len(fills)
                        continue
                    if is_snapshot is True:
                        stats.snapshots_ignored += len(fills)
                        continue
                    if not wallet or wallet not in selected or not fills:
                        continue
                    if wallet not in acknowledged_wallets:
                        stats.unacked_fills_ignored += len(fills)
                        stats.warnings.append(
                            f"fill quarantined for {wallet}: subscription ACK not observed"
                        )
                        continue
                    received = now_ms()
                    enriched = []
                    for fill in fills:
                        e = dict(fill)
                        e["_hypersmart_source"] = "hyperliquid_ws:userFills:stream"
                        e["_hypersmart_ws_received_at_ms"] = received
                        e["_hypersmart_ws_is_snapshot"] = False
                        e["_hypersmart_ws_ack_received_at_ms"] = ack_received_at_ms[wallet]
                        e["_hypersmart_ws_connection_id"] = connection_id
                        payload = _decode_ws_message(message)
                        sequence = payload.get("sequence") if payload else None
                        if type(sequence) is int and sequence >= 0:
                            e["_hypersmart_ws_frame_sequence"] = sequence
                        enriched.append(e)
                        ft = _safe_positive_int(fill.get("time") or fill.get("timestamp"))
                        if ft is not None:
                            stats.last_fill_age_ms = max(0, received - ft)
                    try:
                        await _store_fresh_fills(
                            session_factory, wallet, enriched,
                            max_live_fill_age_ms=max_live_fill_age_ms,
                            stats=stats,
                            sleep=sleep,
                        )
                    except Exception as exc:  # noqa: BLE001
                        stats.warnings.append(f"store failed: {exc}")
            finally:
                if acknowledged_wallets != set(selected):
                    stats.connections_without_complete_ack += 1
                try:
                    # Une fermeture qui pend ne doit pas geler non plus.
                    await asyncio.wait_for(cm.__aexit__(None, None, None), timeout=5.0)
                except Exception:  # noqa: BLE001
                    _noter_echec("hl_observer/wallets/user_fills_live.py:367")
        except Exception as exc:  # noqa: BLE001 - reconnect on any transport error
            stats.warnings.append(f"ws error: {exc}")
        if _stopped():
            stats.stopped_reason = "stopped"
            break
        stats.reconnects += 1
        if max_reconnects is not None and stats.reconnects > max_reconnects:
            stats.stopped_reason = "max_reconnects"
            break
        if asyncio.get_running_loop().time() - connected_at >= 5.0:
            attempt = 0  # only stable connections reset the consecutive-failure backoff
        idx = min(attempt, len(backoff_schedule_s) - 1)
        attempt += 1
        base_delay = max(0.01, float(backoff_schedule_s[idx]))
        jittered_delay = random.uniform(base_delay * 0.8, base_delay * 1.2)
        await sleep(max(0.01, jittered_delay))
    return stats


__all__ = [
    "UserFillsLiveResult", "normalize_user_fill_wallets", "user_fills_from_message",
    "user_fills_subscription_ack",
    "classify_snapshot_fill_entry",
    "scan_user_fills_ws", "store_user_fills_live_result", "format_user_fills_live_report",
    "StreamStats", "stream_user_fills_ws",
]
