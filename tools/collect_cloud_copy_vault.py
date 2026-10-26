#!/usr/bin/env python3
"""Bounded GitHub-hosted Copy-Vault collection window.

Fresh-data rule:
- discover the public observation universe at t0;
- select deterministic observation-only vaults from that t0 snapshot;
- collect userFills forward from t0 over public WebSocket subscriptions;
- reconcile ONLY [t0, t1] with public userFillsByTime after the window;
- never use pre-selection history as forward evidence.

No key, signature, order, deposit, withdrawal or private endpoint is used.
"""
from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import shutil
import sys
import time
import uuid
from collections import defaultdict, deque
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import httpx
import websockets

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
sys.path.insert(0, str(ROOT / "src"))

import collecter_vaults as CV  # noqa: E402

from hl_observer.collection.partitioned_tick_dataset import (  # noqa: E402
    PartitionedTickDatasetWriter,
)
from hl_observer.collection.tick_dataset import TickEnvelope  # noqa: E402
from hl_observer.collection.userfills_live import parser_message_userfills  # noqa: E402
from hl_observer.collection.vault_fills_backfill import (  # noqa: E402
    CAP_USERFILLS,
    canonical_fill_id,
    dedupliquer,
    parser_fills,
)
from hl_observer.datasets.v2_export import (  # noqa: E402
    build_manifest_from_tick_shard,
    write_manifest,
)
from hl_observer.datasets.v2_pipeline import (  # noqa: E402
    V2_REPOSITORY,
    V2_SCHEMA,
    admission_rejection,
    finalize_manifest,
    infer_reconciliation_status,
    locally_replay_admissible,
    summarize_admission_rejections,
)
from hl_observer.realtime.feed_quality import FeedEventKind  # noqa: E402

WS_URL = "wss://api.hyperliquid.xyz/ws"
INFO_URL = "https://api.hyperliquid.xyz/info"
MAX_SUBSCRIPTIONS_PER_SOCKET = 5
MAX_UNIQUE_USERS_PER_IP = 10
MAX_RECONCILIATION_REQUESTS_PER_VAULT = 512
RECONCILIATION_PER_VAULT_TIMEOUT_S = 90.0
# Hyperliquid shares the 1200 weight/minute REST limit across /info calls.
# Keep this collector's coordinated budget at 1080 to leave recovery headroom.
REST_WEIGHT_BUDGET_PER_MINUTE = 1_080
BROAD_SWEEP_REQUEST_INTERVAL_S = 0.14
BROAD_SWEEP_CONCURRENCY = 8
MAX_PRIORITY_WS_VAULTS = 10
PRIORITY_AUDIT_ROTATION_SLOTS = 2
DEFAULT_HISTORY_LOOKBACK_HOURS = 72.0
MAX_HISTORY_LOOKBACK_HOURS = 72.0
MAX_PUBLIC_USERFILLS = 10_000
MAX_USERFILLS_RESPONSE_WEIGHT = 20 + CAP_USERFILLS // 20


class RestWeightPacer:
    """Coordinate this collector's public /info requests under one weight budget."""

    def __init__(
        self,
        *,
        budget_weight_per_minute: int = REST_WEIGHT_BUDGET_PER_MINUTE,
        monotonic_fn: Any = time.monotonic,
        sleep_fn: Any = asyncio.sleep,
    ) -> None:
        budget = int(budget_weight_per_minute)
        if not 1 <= budget <= 1_200:
            raise ValueError("REST weight budget must be in 1..1200 per minute")
        self.budget_weight_per_minute = budget
        self._monotonic = monotonic_fn
        self._sleep = sleep_fn
        self._next_at = 0.0
        self._lock = asyncio.Lock()

    async def acquire_weight(self, weight: int) -> None:
        requested = max(1, int(weight))
        async with self._lock:
            now = float(self._monotonic())
            delay = max(0.0, self._next_at - now)
            if delay > 0:
                await self._sleep(delay)
            now = float(self._monotonic())
            self._next_at = max(now, self._next_at) + (
                60.0 * requested / self.budget_weight_per_minute
            )

    async def before_request(self) -> None:
        # Reserve the maximum possible weight before sending to stay safe when
        # several large responses arrive concurrently (20 + 2000 / 20).
        await self.acquire_weight(MAX_USERFILLS_RESPONSE_WEIGHT)


class AsyncTickSink:
    def __init__(
        self,
        writer: PartitionedTickDatasetWriter,
        *,
        max_queue: int = 100_000,
        batch_size: int = 2_000,
    ) -> None:
        self.writer = writer
        self.queue: asyncio.Queue[TickEnvelope] = asyncio.Queue(maxsize=max_queue)
        self.batch_size = max(1, int(batch_size))
        self.accepted = 0
        self.persisted = 0
        self.backpressure_events = 0
        self.drops: dict[tuple[str, str, str], int] = defaultdict(int)
        self._stop = False

    @staticmethod
    def key(envelope: TickEnvelope) -> tuple[str, str, str]:
        return (
            str(envelope.source_id),
            str(envelope.channel),
            str(envelope.instrument),
        )

    def emit(self, envelope: TickEnvelope) -> None:
        # Legacy callback: congestion remains explicit, never silently ignored.
        try:
            self.queue.put_nowait(envelope)
            self.accepted += 1
        except asyncio.QueueFull:
            self.drops[self.key(envelope)] += 1

    async def emit_async(self, envelope: TickEnvelope) -> None:
        # Async capture should wait for a durable writer slot instead of
        # silently losing a causally significant fill/position observation.
        if self.queue.full():
            self.backpressure_events += 1
        await self.queue.put(envelope)
        self.accepted += 1

    async def run(self) -> None:
        while not self._stop or not self.queue.empty():
            try:
                first = await asyncio.wait_for(self.queue.get(), timeout=0.25)
            except TimeoutError:
                continue
            batch = [first]
            while len(batch) < self.batch_size:
                try:
                    batch.append(self.queue.get_nowait())
                except asyncio.QueueEmpty:
                    break
            records = await asyncio.to_thread(self.writer.append_batch_records, batch)
            self.persisted += len(records)
            for _ in batch:
                self.queue.task_done()

    async def close(self) -> None:
        self._stop = True
        await self.queue.join()


async def _emit_with_backpressure(sink: Any, envelope: TickEnvelope) -> None:
    async_emit = getattr(sink, "emit_async", None)
    if callable(async_emit):
        await async_emit(envelope)
    else:
        sink.emit(envelope)


def discover_vaults(
    *,
    max_vaults: int,
    min_tvl_usd: float = CV.MIN_TVL_PUBLIC_USD,
    min_age_days: float = CV.MIN_AGE_PUBLIC_DAYS,
    now_ms: int | None = None,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Fetch and freeze one public observation universe at selection time."""
    selected_at_ms = int(time.time() * 1_000) if now_ms is None else int(now_ms)
    raw = CV._get_vaults_public()
    rows = CV.parser_univers_public(
        raw,
        now_ms=selected_at_ms,
        min_tvl_usd=min_tvl_usd,
        min_age_days=min_age_days,
        max_vaults=max(1, int(max_vaults)),
    )
    if not rows:
        raise RuntimeError("public Copy-Vault observation universe is empty")
    selection = {
        "schema": "alina.copy_vault_selection.v1",
        "selected_at_ms": selected_at_ms,
        "source": CV.URL_VAULTS,
        "filters": {
            "min_tvl_usd": float(min_tvl_usd),
            "min_age_days": float(min_age_days),
            "max_vaults": int(max_vaults),
            "relationship": "normal",
            "is_closed": False,
        },
        "vault_count": len(rows),
        "vaults": rows,
        "observation_only": True,
        "read_only": True,
        "real_execution": False,
    }
    return rows, selection


def selection_envelope(row: Mapping[str, Any], selection: Mapping[str, Any]) -> TickEnvelope:
    vault = str(row["address"]).lower()
    selected_at_ms = int(selection["selected_at_ms"])
    return TickEnvelope(
        source_id="hyperliquid_public_vaults",
        channel="copy_vault_selection",
        instrument=vault,
        event_kind=FeedEventKind.SNAPSHOT,
        raw_payload={
            "selection": dict(row),
            "filters": dict(selection["filters"]),
        },
        exchange_ts_ms=None,
        received_ts_ms=selected_at_ms,
        local_monotonic_ns=time.monotonic_ns(),
        connection_id=None,
        sequence=None,
        provenance={
            "url": str(selection["source"]),
            "network": "mainnet",
            "access": "read_only",
            "transport": "https",
            "authenticated": False,
            "selection_causal": True,
            "timestamp_semantics": "receive_observation_time_only",
        },
        parsed_summary={
            "tvl_usd": row.get("tvl_usd"),
            "age_days": row.get("age_j"),
            "apr_pct_display_only": row.get("apr_pct"),
            "observation_only": True,
            "selected_at_ms": selected_at_ms,
            "data_gate_ready": False,
        },
    )


def userfills_envelope(
    message: Mapping[str, Any],
    *,
    vault: str,
    receive_wall_ms: int,
    receive_mono_ns: int,
    connection_id: str,
) -> tuple[TickEnvelope | None, list[dict[str, Any]]]:
    fills = parser_message_userfills(
        message,
        vault=vault,
        received_at_ms=receive_wall_ms,
        receive_mono_ns=receive_mono_ns,
        connection_id=connection_id,
    )
    if not fills:
        return None, []
    data = message.get("data")
    is_snapshot = bool(data.get("isSnapshot")) if isinstance(data, Mapping) else False
    exchange_times = [
        int(fill["ts_ms"])
        for fill in fills
        if fill.get("ts_ms") is not None
    ]
    exchange_ts_ms = max(exchange_times) if exchange_times else None
    sequence = None
    for candidate in (
        message.get("sequence"),
        message.get("seq"),
        data.get("sequence") if isinstance(data, Mapping) else None,
        data.get("seq") if isinstance(data, Mapping) else None,
    ):
        try:
            if candidate is not None:
                sequence = int(candidate)
                break
        except (TypeError, ValueError, OverflowError):
            pass

    channel = "copy_vault_snapshot" if is_snapshot else "copy_vault_fills"
    event_kind = FeedEventKind.SNAPSHOT if is_snapshot else FeedEventKind.EVENT
    return (
        TickEnvelope(
            source_id="hyperliquid_public_userfills",
            channel=channel,
            instrument=vault.lower(),
            event_kind=event_kind,
            raw_payload=dict(message),
            exchange_ts_ms=exchange_ts_ms,
            received_ts_ms=receive_wall_ms,
            local_monotonic_ns=receive_mono_ns,
            connection_id=connection_id,
            sequence=sequence,
            provenance={
                "url": WS_URL,
                "network": "mainnet",
                "access": "read_only",
                "transport": "websocket",
                "authenticated": False,
                "selection_causal": True,
            },
            parsed_summary={
                "event_count": len(fills),
                "is_snapshot": is_snapshot,
                "first_fill_ts_ms": min(exchange_times) if exchange_times else None,
                "last_fill_ts_ms": exchange_ts_ms,
                "data_gate_ready": False,
            },
        ),
        fills,
    )


def l2_envelope(
    message: Mapping[str, Any],
    *,
    receive_wall_ms: int,
    receive_mono_ns: int,
    connection_id: str,
    reconnect_count: int = 0,
) -> TickEnvelope | None:
    if str(message.get("channel") or "") != "l2Book":
        return None
    data = message.get("data")
    if not isinstance(data, Mapping):
        return None
    coin = str(data.get("coin") or "").strip().upper()
    if not coin:
        return None
    try:
        exchange_ts_ms = int(data.get("time")) if data.get("time") is not None else None
    except (TypeError, ValueError, OverflowError):
        exchange_ts_ms = None
    levels = data.get("levels")
    bid_levels = ask_levels = 0
    if isinstance(levels, list):
        if len(levels) > 0 and isinstance(levels[0], list):
            bid_levels = len(levels[0])
        if len(levels) > 1 and isinstance(levels[1], list):
            ask_levels = len(levels[1])
    return TickEnvelope(
        source_id="hyperliquid_public_copy_l2",
        channel="copy_vault_l2",
        instrument=coin,
        event_kind=FeedEventKind.SNAPSHOT,
        raw_payload=dict(message),
        exchange_ts_ms=exchange_ts_ms,
        received_ts_ms=receive_wall_ms,
        local_monotonic_ns=receive_mono_ns,
        connection_id=connection_id,
        reconnect_count=int(reconnect_count),
        provenance={
            "url": WS_URL,
            "network": "mainnet",
            "access": "read_only",
            "transport": "websocket",
            "authenticated": False,
            "copy_vault_execution_evidence": True,
        },
        parsed_summary={
            "bid_levels": bid_levels,
            "ask_levels": ask_levels,
            "data_gate_ready": False,
        },
    )


async def _dynamic_l2_collector(
    sink: AsyncTickSink,
    request_queue: asyncio.Queue[str],
    known_coins: set[str],
    state: dict[str, int],
) -> None:
    """Maintain one public HL L2 socket and dynamically subscribe leader coins."""
    attempt = 0
    while True:
        connection_id = f"copy-l2-{uuid.uuid4().hex}"
        try:
            async with websockets.connect(
                WS_URL,
                ping_interval=20,
                ping_timeout=10,
                close_timeout=5,
                max_size=2**23,
            ) as socket:
                subscribed: set[str] = set()
                send_lock = asyncio.Lock()

                async def send_json(
                    payload: Mapping[str, Any],
                    *,
                    _send_lock: asyncio.Lock = send_lock,
                    _socket: Any = socket,
                ) -> None:
                    async with _send_lock:
                        await _socket.send(json.dumps(dict(payload)))

                for coin in sorted(known_coins):
                    await send_json(
                        {
                            "method": "subscribe",
                            "subscription": {"type": "l2Book", "coin": coin},
                        }
                    )
                    subscribed.add(coin)
                    await asyncio.sleep(0.03)

                async def sender(
                    *,
                    _subscriptions: set[str] = subscribed,
                    _queue: asyncio.Queue[str] = request_queue,
                    _send: Any = send_json,
                ) -> None:
                    while True:
                        coin = str(await _queue.get()).strip().upper()
                        try:
                            if coin and coin not in _subscriptions:
                                await _send(
                                    {
                                        "method": "subscribe",
                                        "subscription": {
                                            "type": "l2Book",
                                            "coin": coin,
                                        },
                                    }
                                )
                                _subscriptions.add(coin)
                        finally:
                            _queue.task_done()

                async def heartbeat() -> None:
                    while True:
                        await asyncio.sleep(30.0)
                        await send_json({"method": "ping"})
                        state["heartbeats"] = state.get("heartbeats", 0) + 1

                sender_task = asyncio.create_task(sender())
                heartbeat_task = asyncio.create_task(heartbeat())
                attempt = 0
                try:
                    async for raw_text in socket:
                        mono = time.monotonic_ns()
                        wall = int(time.time() * 1_000)
                        try:
                            message = json.loads(raw_text)
                        except (TypeError, ValueError):
                            continue
                        if not isinstance(message, Mapping):
                            continue
                        envelope = l2_envelope(
                            message,
                            receive_wall_ms=wall,
                            receive_mono_ns=mono,
                            connection_id=connection_id,
                            reconnect_count=state.get("reconnects", 0),
                        )
                        if envelope is not None:
                            await _emit_with_backpressure(sink, envelope)
                            state["frames"] = state.get("frames", 0) + 1
                finally:
                    sender_task.cancel()
                    heartbeat_task.cancel()
                    await asyncio.gather(
                        sender_task,
                        heartbeat_task,
                        return_exceptions=True,
                    )
        except asyncio.CancelledError:
            raise
        except Exception:
            state["reconnects"] = state.get("reconnects", 0) + 1
            await asyncio.sleep(min(30.0, 2.0 ** min(attempt, 5)))
            attempt += 1


def validate_user_subscription_budget(vaults: list[str]) -> int:
    """Enforce Hyperliquid's per-IP unique user subscription ceiling."""
    unique = {
        str(vault).strip().lower()
        for vault in vaults
        if str(vault).strip()
    }
    count = len(unique)
    if count > MAX_UNIQUE_USERS_PER_IP:
        raise ValueError(
            f"Copy-Vault lane has {count} unique users; "
            f"Hyperliquid limit is {MAX_UNIQUE_USERS_PER_IP} per IP"
        )
    return count



class _RequestRateGate:
    """Monotonic request spacing shared by all broad-sweep workers."""

    def __init__(self, interval_s: float) -> None:
        self.interval_s = max(0.0, float(interval_s))
        self._next_at = 0.0
        self._lock = asyncio.Lock()

    async def wait(self) -> None:
        async with self._lock:
            now = time.monotonic()
            slot = max(now, self._next_at)
            self._next_at = slot + self.interval_s
        delay = slot - now
        if delay > 0:
            await asyncio.sleep(delay)


def _position_fingerprint(state: Mapping[str, Any]) -> str:
    rows = []
    for raw in state.get("positions") or []:
        if not isinstance(raw, Mapping):
            continue
        rows.append(
            {
                "coin": str(raw.get("coin") or "").upper(),
                "szi": raw.get("szi"),
                "entryPx": raw.get("entryPx"),
                "levier": raw.get("levier"),
            }
        )
    rows.sort(key=lambda row: (row["coin"], str(row["szi"])))
    return hashlib.sha256(
        json.dumps(rows, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def broad_state_envelope(
    payload: Mapping[str, Any],
    *,
    vault: str,
    phase: str,
    receive_wall_ms: int,
    receive_mono_ns: int,
) -> tuple[TickEnvelope | None, dict[str, Any] | None]:
    """Normalize one broad clearinghouseState observation into one compact family.

    All broad-state records intentionally use instrument='*' so thousands of vaults
    stay in a small number of Dataset V2 shards instead of creating one release
    asset per vault. The exact vault address remains in raw/parsed evidence.
    """
    parsed = CV.parser_clearinghouse(dict(payload))
    if parsed is None:
        return None, None
    fingerprint = _position_fingerprint(parsed)
    try:
        exchange_ts_ms = int(payload.get("time")) if payload.get("time") is not None else None
    except (TypeError, ValueError, OverflowError):
        exchange_ts_ms = None
    summary = {
        "vault": str(vault).lower(),
        "phase": str(phase).upper(),
        "position_fingerprint": fingerprint,
        "nav_usd": parsed.get("nav_usd"),
        "expo_brute_usd": parsed.get("expo_brute_usd"),
        "expo_nette_usd": parsed.get("expo_nette_usd"),
        "levier": parsed.get("levier"),
        "n_positions": parsed.get("n_positions"),
        "data_gate_ready": False,
    }
    envelope = TickEnvelope(
        source_id="hyperliquid_public_info",
        channel="copy_vault_broad_state",
        instrument="*",
        event_kind=FeedEventKind.SNAPSHOT,
        raw_payload={
            "vault": str(vault).lower(),
            "phase": str(phase).upper(),
            "clearinghouseState": dict(payload),
        },
        exchange_ts_ms=exchange_ts_ms,
        received_ts_ms=receive_wall_ms,
        local_monotonic_ns=receive_mono_ns,
        connection_id=None,
        sequence=None,
        provenance={
            "url": INFO_URL,
            "network": "mainnet",
            "access": "read_only",
            "transport": "https",
            "authenticated": False,
            "request_type": "clearinghouseState",
            "broad_sweep": True,
        },
        parsed_summary=summary,
    )
    return envelope, {**summary, "positions": parsed.get("positions") or []}


async def collect_broad_state(
    rows: list[Mapping[str, Any]],
    sink: AsyncTickSink,
    *,
    phase: str,
    request_interval_s: float = BROAD_SWEEP_REQUEST_INTERVAL_S,
    concurrency: int = BROAD_SWEEP_CONCURRENCY,
    http_client: httpx.AsyncClient | None = None,
    pacer: RestWeightPacer | None = None,
) -> dict[str, Any]:
    """Rate-budgeted complete-universe clearinghouseState sweep.

    The official clearinghouseState request weight is 2. Production spacing is
    deliberately below the per-IP 1200 weight/min limit. Failures remain visible
    and never fabricate state.
    """
    started = time.monotonic()
    gate = _RequestRateGate(request_interval_s)
    semaphore = asyncio.Semaphore(max(1, int(concurrency)))
    owns_client = http_client is None
    client = http_client or httpx.AsyncClient(
        base_url="https://api.hyperliquid.xyz",
        timeout=15.0,
    )
    states: dict[str, dict[str, Any]] = {}
    failures: dict[str, int] = defaultdict(int)

    async def one(row: Mapping[str, Any]) -> None:
        vault = str(row.get("address") or "").strip().lower()
        if not vault:
            failures["MISSING_ADDRESS"] += 1
            return
        async with semaphore:
            last_error = "UNKNOWN"
            for attempt in range(2):
                if pacer is None:
                    await gate.wait()
                try:
                    if pacer is not None:
                        await pacer.acquire_weight(2)
                    response = await client.post(
                        "/info",
                        json={"type": "clearinghouseState", "user": vault},
                    )
                    response.raise_for_status()
                    payload = response.json()
                except Exception as exc:
                    last_error = type(exc).__name__
                    if attempt == 0:
                        await asyncio.sleep(0.5)
                        continue
                    failures[last_error] += 1
                    return
                if not isinstance(payload, Mapping):
                    failures["INVALID_PAYLOAD"] += 1
                    return
                receive_mono_ns = time.monotonic_ns()
                receive_wall_ms = int(time.time() * 1_000)
                envelope, state = broad_state_envelope(
                    payload,
                    vault=vault,
                    phase=phase,
                    receive_wall_ms=receive_wall_ms,
                    receive_mono_ns=receive_mono_ns,
                )
                if envelope is None or state is None:
                    failures["UNPARSABLE_STATE"] += 1
                    return
                state["tvl_usd"] = float(row.get("tvl_usd") or 0.0)
                states[vault] = state
                await _emit_with_backpressure(sink, envelope)
                return
            failures[last_error] += 1

    try:
        await asyncio.gather(*(one(row) for row in rows))
    finally:
        if owns_client:
            await client.aclose()

    return {
        "phase": str(phase).upper(),
        "requested": len(rows),
        "observed": len(states),
        "failed": max(0, len(rows) - len(states)),
        "failure_types": dict(sorted(failures.items())),
        "elapsed_s": round(time.monotonic() - started, 3),
        "request_interval_s": float(request_interval_s),
        "states": states,
    }


def select_priority_ws_vaults(
    rows: list[Mapping[str, Any]],
    broad_sweep: Mapping[str, Any],
    *,
    max_ws_vaults: int = MAX_PRIORITY_WS_VAULTS,
    rotation_seed: str = "",
) -> list[dict[str, Any]]:
    """Pick scarce WS users from broad state, plus deterministic audit rotation."""
    limit = max(1, min(MAX_PRIORITY_WS_VAULTS, int(max_ws_vaults)))
    states = broad_sweep.get("states")
    if not isinstance(states, Mapping) or not states:
        raise RuntimeError("broad Copy-Vault sweep produced no usable state")
    by_address = {
        str(row.get("address") or "").strip().lower(): dict(row)
        for row in rows
        if isinstance(row, Mapping) and str(row.get("address") or "").strip()
    }
    observed = [
        address for address in by_address
        if isinstance(states.get(address), Mapping)
    ]
    if not observed:
        raise RuntimeError("no frozen Copy-Vault address has observed broad state")

    audit_slots = min(PRIORITY_AUDIT_ROTATION_SLOTS, limit)
    core_slots = max(0, limit - audit_slots)

    def activity_key(address: str) -> tuple[float, float, float, str]:
        state = states[address]
        return (
            -float(state.get("n_positions") or 0),
            -float(state.get("expo_brute_usd") or 0.0),
            -float(by_address[address].get("tvl_usd") or 0.0),
            address,
        )

    active = [
        address for address in observed
        if int(states[address].get("n_positions") or 0) > 0
    ]
    active.sort(key=activity_key)
    selected = active[:core_slots]

    if len(selected) < core_slots:
        fill = [address for address in observed if address not in selected]
        fill.sort(key=activity_key)
        selected.extend(fill[: core_slots - len(selected)])

    remaining = [address for address in observed if address not in selected]
    remaining.sort(
        key=lambda address: hashlib.sha256(
            f"{rotation_seed}|{address}".encode()
        ).hexdigest()
    )
    selected.extend(remaining[: max(0, limit - len(selected))])

    result: list[dict[str, Any]] = []
    for index, address in enumerate(selected[:limit]):
        row = dict(by_address[address])
        state = states[address]
        row["ws_selection_reason"] = (
            "ACTIVE_PRIORITY" if address in active[:core_slots] else "AUDIT_ROTATION"
        )
        row["broad_n_positions"] = int(state.get("n_positions") or 0)
        row["broad_expo_brute_usd"] = float(state.get("expo_brute_usd") or 0.0)
        row["broad_position_fingerprint"] = str(
            state.get("position_fingerprint") or ""
        )
        row["ws_priority_rank"] = index
        result.append(row)
    return result


def _compact_sweep_metrics(sweep: Mapping[str, Any]) -> dict[str, Any]:
    return {
        key: value
        for key, value in sweep.items()
        if key != "states"
    }


async def collect_position_snapshots(
    vaults: list[str],
    sink: AsyncTickSink,
    *,
    phase: str,
    pacer: RestWeightPacer | None = None,
) -> int:
    """Capture public clearinghouse state as a leader-position anchor."""
    semaphore = asyncio.Semaphore(8)
    count = 0

    async with httpx.AsyncClient(
        base_url="https://api.hyperliquid.xyz",
        timeout=15.0,
    ) as client:
        async def one(vault: str) -> TickEnvelope | None:
            async with semaphore:
                sent_ms = int(time.time() * 1_000)
                try:
                    if pacer is not None:
                        await pacer.acquire_weight(2)
                    response = await client.post(
                        "/info",
                        json={"type": "clearinghouseState", "user": vault},
                    )
                    response.raise_for_status()
                    payload = response.json()
                except Exception:
                    return None
                mono = time.monotonic_ns()
                received_ms = int(time.time() * 1_000)
                if not isinstance(payload, Mapping):
                    return None
                positions = payload.get("assetPositions")
                position_count = len(positions) if isinstance(positions, list) else 0
                return TickEnvelope(
                    source_id="hyperliquid_public_info",
                    channel="copy_vault_positions",
                    instrument=vault,
                    event_kind=FeedEventKind.SNAPSHOT,
                    raw_payload=dict(payload),
                    exchange_ts_ms=None,
                    received_ts_ms=received_ms,
                    local_monotonic_ns=mono,
                    connection_id=None,
                    provenance={
                        "url": INFO_URL,
                        "network": "mainnet",
                        "access": "read_only",
                        "transport": "https",
                        "authenticated": False,
                        "request_type": "clearinghouseState",
                        "timestamp_semantics": "receive_observation_time_only",
                        "request_send_wall_ms": sent_ms,
                        "request_receive_wall_ms": received_ms,
                    },
                    parsed_summary={
                        "phase": phase,
                        "position_count": position_count,
                        "data_gate_ready": False,
                    },
                )

        rows = await asyncio.gather(*(one(vault) for vault in vaults))
        for envelope in rows:
            if envelope is not None:
                await _emit_with_backpressure(sink, envelope)
                count += 1
    return count


async def _socket_group(
    vaults: list[str],
    sink: AsyncTickSink,
    *,
    observation_start_ms: dict[str, int],
    live_ids: dict[str, set[str]],
    live_fill_counts: dict[str, int],
    reconnect_counts: dict[str, int],
    l2_request_queue: asyncio.Queue[str],
    l2_known_coins: set[str],
) -> None:
    attempt = 0
    known = {vault.lower(): vault.lower() for vault in vaults}
    while True:
        connection_id = f"copy-vault-{uuid.uuid4().hex}"
        try:
            async with websockets.connect(
                WS_URL,
                ping_interval=20,
                ping_timeout=10,
                close_timeout=5,
                max_size=2**23,
            ) as socket:
                send_lock = asyncio.Lock()

                async def send_json(
                    payload: Mapping[str, Any],
                    *,
                    _send_lock: asyncio.Lock = send_lock,
                    _socket: Any = socket,
                ) -> None:
                    async with _send_lock:
                        await _socket.send(json.dumps(dict(payload)))

                for vault in vaults:
                    await send_json(
                        {
                            "method": "subscribe",
                            "subscription": {
                                "type": "userFills",
                                "user": vault,
                            },
                        }
                    )
                    observation_start_ms.setdefault(
                        vault,
                        int(time.time() * 1_000),
                    )
                    await asyncio.sleep(0.15)

                async def heartbeat() -> None:
                    while True:
                        await asyncio.sleep(30.0)
                        await send_json({"method": "ping"})

                heartbeat_task = asyncio.create_task(heartbeat())
                attempt = 0
                try:
                    async for raw_text in socket:
                        mono = time.monotonic_ns()
                        wall = int(time.time() * 1_000)
                        try:
                            message = json.loads(raw_text)
                        except (TypeError, ValueError):
                            continue
                        if not isinstance(message, Mapping):
                            continue
                        if message.get("channel") in {"subscriptionResponse", "pong"}:
                            continue

                        data = message.get("data")
                        user = (
                            str(data.get("user") or "").lower()
                            if isinstance(data, Mapping)
                            else ""
                        )
                        vault = known.get(user)
                        if vault is None:
                            continue

                        envelope, fills = userfills_envelope(
                            message,
                            vault=vault,
                            receive_wall_ms=wall,
                            receive_mono_ns=mono,
                            connection_id=connection_id,
                        )
                        if envelope is None:
                            continue
                        envelope.reconnect_count = reconnect_counts.get(vault, 0)
                        await _emit_with_backpressure(sink, envelope)

                        # Pre-warm public execution L2 from every observed coin,
                        # including the initial snapshot. Snapshot fills never count
                        # as forward copy signals.
                        for fill in fills:
                            coin = str(fill.get("coin") or "").strip().upper()
                            if coin and coin not in l2_known_coins:
                                l2_known_coins.add(coin)
                                l2_request_queue.put_nowait(coin)

                        # Selection time is only universe provenance. Forward
                        # reconciliation starts when this hosted lane can observe.
                        if envelope.channel != "copy_vault_fills":
                            continue
                        for fill in fills:
                            try:
                                ts_ms = int(fill.get("ts_ms") or 0)
                            except (TypeError, ValueError, OverflowError):
                                continue
                            start_ms = observation_start_ms.get(vault)
                            if start_ms is None or ts_ms < int(start_ms):
                                continue
                            live_ids[vault].add(canonical_fill_id(fill))
                            live_fill_counts[vault] += 1
                finally:
                    heartbeat_task.cancel()
                    await asyncio.gather(heartbeat_task, return_exceptions=True)
        except asyncio.CancelledError:
            raise
        except Exception:
            for vault in vaults:
                reconnect_counts[vault] += 1
            await asyncio.sleep(min(30.0, 2.0 ** min(attempt, 5)))
            attempt += 1


async def _post_userfills(
    client: httpx.AsyncClient,
    vault: str,
    start_ms: int,
    end_ms: int,
) -> list[dict[str, Any]]:
    response = await client.post(
        "/info",
        json={
            "type": "userFillsByTime",
            "user": vault,
            "startTime": int(start_ms),
            "endTime": int(end_ms),
            "aggregateByTime": False,
        },
    )
    response.raise_for_status()
    payload = response.json()
    if not isinstance(payload, list):
        raise ValueError("userFillsByTime returned non-list")
    return [row for row in payload if isinstance(row, dict)]


async def exact_window_backfill(
    client: httpx.AsyncClient,
    vault: str,
    *,
    start_ms: int,
    end_ms: int,
    min_window_ms: int = 1_000,
    max_requests: int = MAX_RECONCILIATION_REQUESTS_PER_VAULT,
    pacer: RestWeightPacer | None = None,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Adaptive exact-window REST reconciliation using the 2,000 response cap."""
    pending: deque[tuple[int, int]] = deque([(int(start_ms), int(end_ms))])
    accepted: list[dict[str, Any]] = []
    failures: list[dict[str, Any]] = []
    capped_minimum: list[dict[str, Any]] = []
    requests = 0
    splits = 0
    request_budget_exhausted = False
    invalid_fill_count = 0

    while pending:
        if requests >= max(1, int(max_requests)):
            request_budget_exhausted = True
            break
        left, right = pending.popleft()
        requests += 1
        try:
            if pacer is not None:
                await pacer.before_request()
            raw = await _post_userfills(client, vault, left, right)
        except Exception as exc:
            failures.append(
                {
                    "start_ms": left,
                    "end_ms": right,
                    "error": type(exc).__name__,
                }
            )
            continue
        if len(raw) >= CAP_USERFILLS:
            span = right - left
            if span <= int(min_window_ms):
                capped_minimum.append(
                    {
                        "start_ms": left,
                        "end_ms": right,
                        "rows": len(raw),
                        "cap": CAP_USERFILLS,
                    }
                )
                parsed = parser_fills(raw, vault=vault, include_raw=True)
                invalid_fill_count += len(raw) - len(parsed)
                accepted.extend(parsed)
                continue
            middle = left + max(1, span // 2)
            pending.appendleft((middle, right))
            pending.appendleft((left, middle))
            splits += 1
            continue
        parsed = parser_fills(raw, vault=vault, include_raw=True)
        invalid_fill_count += len(raw) - len(parsed)
        accepted.extend(parsed)

    rows = dedupliquer(accepted)
    retention_cap_reached = len(rows) >= MAX_PUBLIC_USERFILLS
    fill_times = [
        int(row["ts_ms"])
        for row in rows
        if type(row.get("ts_ms")) is int and int(row["ts_ms"]) > 0
    ]
    return rows, {
        "status": (
            "COMPLETE"
            if not failures
            and not capped_minimum
            and not request_budget_exhausted
            and not invalid_fill_count
            and not retention_cap_reached
            else "PARTIAL"
        ),
        "requested_start_ms": int(start_ms),
        "requested_end_ms": int(end_ms),
        "requests": requests,
        "splits": splits,
        "failed_windows": failures,
        "cap_blocked_windows": capped_minimum,
        "request_budget_exhausted": request_budget_exhausted,
        "pending_windows": len(pending),
        "invalid_fill_count": invalid_fill_count,
        "retention_cap_reached": retention_cap_reached,
        "oldest_fill_ts_ms": min(fill_times) if fill_times else None,
        "newest_fill_ts_ms": max(fill_times) if fill_times else None,
        "rows": len(rows),
    }


def rest_backfill_envelopes(
    rows: list[Mapping[str, Any]],
    *,
    vault: str,
    audit: Mapping[str, Any],
    receive_wall_ms: int,
    receive_mono_ns: int,
) -> list[TickEnvelope]:
    """Preserve exact public REST fills as historical snapshots, never forward signals."""
    vault_id = str(vault or "").strip().lower()
    if not vault_id or int(receive_wall_ms) <= 0 or int(receive_mono_ns) <= 0:
        raise ValueError("historical backfill requires vault and receive clocks")
    raw_fills: list[dict[str, Any]] = []
    for row in rows:
        raw = row.get("raw_fill") if isinstance(row, Mapping) else None
        if not isinstance(raw, Mapping):
            raise ValueError("historical backfill is missing its original fill payload")
        try:
            event_ms = int(raw["time"])
        except (KeyError, TypeError, ValueError, OverflowError) as exc:
            raise ValueError("historical fill is missing its exchange timestamp") from exc
        if not 0 < event_ms <= int(receive_wall_ms):
            raise ValueError("historical fill timestamp is future or invalid")
        raw_fills.append(dict(raw))

    envelopes: list[TickEnvelope] = []
    for offset in range(0, len(raw_fills), CAP_USERFILLS):
        batch = raw_fills[offset : offset + CAP_USERFILLS]
        exchange_ts_ms = max(int(fill["time"]) for fill in batch)
        envelopes.append(
            TickEnvelope(
                source_id="hyperliquid_public_userfills_backfill",
                channel="copy_vault_snapshot",
                instrument=vault_id,
                event_kind=FeedEventKind.SNAPSHOT,
                raw_payload={
                    "channel": "userFills",
                    "data": {
                        "user": vault_id,
                        "isSnapshot": True,
                        "fills": batch,
                    },
                    "backfill_audit": dict(audit),
                },
                exchange_ts_ms=exchange_ts_ms,
                received_ts_ms=int(receive_wall_ms),
                local_monotonic_ns=int(receive_mono_ns),
                connection_id=None,
                sequence=None,
                provenance={
                    "url": INFO_URL,
                    "network": "mainnet",
                    "access": "read_only",
                    "transport": "https",
                    "authenticated": False,
                    "request_type": "userFillsByTime",
                    "forward_evidence_allowed": False,
                    "historical_only": True,
                    "timestamp_semantics": "causal_event_availability",
                },
                parsed_summary={
                    "event_count": len(batch),
                    "fill_count": len(batch),
                    "is_snapshot": True,
                    "historical_only": True,
                    "backfill_status": str(audit.get("status") or "UNAVAILABLE"),
                    "batch_index": offset // CAP_USERFILLS,
                },
            )
        )
    return envelopes


async def reconcile_forward_window(
    vaults: list[str],
    *,
    start_ms_by_vault: Mapping[str, int],
    end_ms: int,
    live_ids: Mapping[str, set[str]],
    pacer: RestWeightPacer | None = None,
) -> dict[str, dict[str, Any]]:
    reports: dict[str, dict[str, Any]] = {}
    async with httpx.AsyncClient(
        base_url="https://api.hyperliquid.xyz",
        timeout=15.0,
    ) as client:
        for vault in vaults:
            start_ms = start_ms_by_vault.get(vault)
            if start_ms is None:
                reports[vault] = {
                    "status": "UNAVAILABLE",
                    "live_count": len(live_ids.get(vault, set())),
                    "reference_count": 0,
                    "matched_count": 0,
                    "missing_from_live": 0,
                    "live_only": len(live_ids.get(vault, set())),
                    "duplicate_live_keys": 0,
                    "audit": {
                        "status": "PARTIAL",
                        "reason": "NO_LIVE_SUBSCRIPTION_START",
                        "requested_start_ms": None,
                        "requested_end_ms": int(end_ms),
                        "rows": 0,
                    },
                }
                continue
            try:
                rows, audit = await asyncio.wait_for(
                    exact_window_backfill(
                        client,
                        vault,
                        start_ms=int(start_ms),
                        end_ms=end_ms,
                        pacer=pacer,
                    ),
                    timeout=RECONCILIATION_PER_VAULT_TIMEOUT_S,
                )
            except TimeoutError:
                observed = set(live_ids.get(vault, set()))
                reports[vault] = {
                    "status": "UNAVAILABLE",
                    "live_count": len(observed),
                    "reference_count": 0,
                    "matched_count": 0,
                    "missing_from_live": 0,
                    "live_only": len(observed),
                    "duplicate_live_keys": 0,
                    "audit": {
                        "status": "PARTIAL",
                        "reason": "REFERENCE_TIMEOUT",
                        "timeout_s": RECONCILIATION_PER_VAULT_TIMEOUT_S,
                        "requested_start_ms": int(start_ms),
                        "requested_end_ms": int(end_ms),
                        "rows": 0,
                    },
                }
                continue
            reference_ids = {
                canonical_fill_id({**row, "vault": vault})
                for row in rows
            }
            observed = set(live_ids.get(vault, set()))
            missing = reference_ids - observed
            live_only = observed - reference_ids
            if audit["status"] != "COMPLETE":
                status = "UNAVAILABLE"
            elif missing:
                status = "MISMATCH"
            elif live_only:
                # Boundary races remain visible and cannot silently certify exactness.
                status = "PARTIAL"
            else:
                status = "MATCHED"
            reports[vault] = {
                "status": status,
                "live_count": len(observed),
                "reference_count": len(reference_ids),
                "matched_count": len(observed & reference_ids),
                "missing_from_live": len(missing),
                "live_only": len(live_only),
                "duplicate_live_keys": 0,
                "audit": audit,
            }
    return reports


async def collect_historical_backfills(
    vaults: list[str],
    *,
    selection_ts_ms: int,
    lookback_hours: float,
    history_checkpoints: Mapping[str, Mapping[str, Any]] | None = None,
    pacer: RestWeightPacer | None = None,
) -> tuple[dict[str, dict[str, Any]], list[TickEnvelope]]:
    """Capture a bounded pre-selection research window, separate from forward receipts."""
    lookback = float(lookback_hours)
    if not 0 < lookback <= MAX_HISTORY_LOOKBACK_HOURS:
        raise ValueError(
            f"history lookback must be within (0,{MAX_HISTORY_LOOKBACK_HOURS}] hours"
        )
    end_ms = int(selection_ts_ms) - 1
    default_start_ms = int(selection_ts_ms - lookback * 3_600_000)
    if default_start_ms <= 0 or end_ms < default_start_ms:
        raise ValueError("selection timestamp cannot support requested history window")

    reports: dict[str, dict[str, Any]] = {}
    envelopes: list[TickEnvelope] = []
    async with httpx.AsyncClient(
        base_url="https://api.hyperliquid.xyz",
        timeout=15.0,
    ) as client:
        for vault in vaults:
            vault_id = str(vault).lower()
            checkpoint = (history_checkpoints or {}).get(vault_id)
            checkpoint_end_ms = (
                checkpoint.get("last_reconciled_end_ms")
                if isinstance(checkpoint, Mapping)
                else None
            )
            if checkpoint_end_ms is None and isinstance(checkpoint, Mapping):
                checkpoint_end_ms = checkpoint.get("last_complete_end_ms")
            unresolved_gaps = (
                [dict(gap) for gap in checkpoint.get("unresolved_gaps", [])
                 if isinstance(gap, Mapping)]
                if isinstance(checkpoint, Mapping)
                and isinstance(checkpoint.get("unresolved_gaps", []), list)
                else []
            )
            start_ms = default_start_ms
            checkpoint_used = False
            checkpoint_from_future = (
                type(checkpoint_end_ms) is int and checkpoint_end_ms > end_ms
            )
            if type(checkpoint_end_ms) is int and 0 < checkpoint_end_ms <= end_ms:
                start_ms = checkpoint_end_ms
                checkpoint_used = True
            elif checkpoint_from_future:
                future_gap = {
                    "start_ms": end_ms + 1,
                    "end_ms": checkpoint_end_ms,
                    "reason": "CHECKPOINT_AFTER_SELECTION_CUTOFF",
                }
                if future_gap not in unresolved_gaps:
                    unresolved_gaps.append(future_gap)
            max_start_ms = end_ms - int(MAX_HISTORY_LOOKBACK_HOURS * 3_600_000)
            if start_ms < max_start_ms:
                gap = {
                    "start_ms": start_ms,
                    "end_ms": max_start_ms - 1,
                    "reason": "HISTORY_LOOKBACK_LIMIT_72H",
                }
                if gap not in unresolved_gaps:
                    unresolved_gaps.append(gap)
                start_ms = max_start_ms
            if start_ms <= 0 or end_ms < start_ms:
                reports[vault_id] = {
                    "status": "PARTIAL",
                    "request_audit_status": "UNAVAILABLE",
                    "reason": "INVALID_HISTORY_WINDOW",
                    "requested_start_ms": start_ms,
                    "requested_end_ms": end_ms,
                    "rows": 0,
                    "checkpoint_advance_allowed": False,
                    "unresolved_gaps": unresolved_gaps,
                    "forward_evidence_allowed": False,
                }
                continue
            try:
                rows, audit = await asyncio.wait_for(
                    exact_window_backfill(
                        client,
                        vault,
                        start_ms=start_ms,
                        end_ms=end_ms,
                        pacer=pacer,
                    ),
                    timeout=RECONCILIATION_PER_VAULT_TIMEOUT_S,
                )
            except TimeoutError:
                audit = {
                    "status": "PARTIAL",
                    "reason": "HISTORICAL_BACKFILL_TIMEOUT",
                    "requested_start_ms": start_ms,
                    "requested_end_ms": end_ms,
                    "rows": 0,
                }
                rows = []
            except Exception as exc:
                audit = {
                    "status": "PARTIAL",
                    "reason": f"HISTORICAL_BACKFILL_{type(exc).__name__}",
                    "requested_start_ms": start_ms,
                    "requested_end_ms": end_ms,
                    "rows": 0,
                }
                rows = []
            request_audit_status = str(audit.get("status") or "PARTIAL").upper()
            retention_window_reconciled = (
                audit.get("retention_cap_reached") is True
                and request_audit_status == "PARTIAL"
                and type(audit.get("rows")) is int
                and int(audit.get("rows") or 0) >= MAX_PUBLIC_USERFILLS
                and type(audit.get("oldest_fill_ts_ms")) is int
                and start_ms <= int(audit.get("oldest_fill_ts_ms") or 0) <= end_ms
                and audit.get("request_budget_exhausted") is False
                and type(audit.get("pending_windows")) is int
                and audit.get("pending_windows") == 0
                and type(audit.get("invalid_fill_count")) is int
                and audit.get("invalid_fill_count") == 0
                and audit.get("failed_windows") == []
                and audit.get("cap_blocked_windows") == []
            )
            if retention_window_reconciled:
                oldest_fill_ms = audit.get("oldest_fill_ts_ms")
                if type(oldest_fill_ms) is int and oldest_fill_ms > start_ms:
                    gap = {
                        "start_ms": start_ms,
                        "end_ms": oldest_fill_ms - 1,
                        "reason": "PUBLIC_10000_FILL_RETENTION_LIMIT",
                    }
                    if gap not in unresolved_gaps:
                        unresolved_gaps.append(gap)
            checkpoint_advance_allowed = (
                (
                    request_audit_status == "COMPLETE"
                    and audit.get("retention_cap_reached") is False
                )
                or retention_window_reconciled
            ) and (
                not checkpoint_from_future
                and audit.get("request_budget_exhausted") is False
                and type(audit.get("pending_windows")) is int
                and audit.get("pending_windows") == 0
                and type(audit.get("invalid_fill_count")) is int
                and audit.get("invalid_fill_count") == 0
                and audit.get("failed_windows") == []
                and audit.get("cap_blocked_windows") == []
            )
            report_status = (
                "COMPLETE"
                if request_audit_status == "COMPLETE" and not unresolved_gaps
                else "PARTIAL"
            )
            report = {
                **dict(audit),
                "status": report_status,
                "request_audit_status": request_audit_status,
                "vault": vault_id,
                "window_kind": (
                    "CONTINUITY_RECONCILIATION"
                    if checkpoint_used
                    else "PRE_SELECTION_HISTORICAL_RESEARCH_ONLY"
                ),
                "lookback_hours": lookback,
                "checkpoint_start_ms": checkpoint_end_ms if checkpoint_used else None,
                "checkpoint_advance_allowed": checkpoint_advance_allowed,
                "unresolved_gaps": unresolved_gaps,
                "forward_evidence_allowed": False,
            }
            reports[vault_id] = report
            if rows:
                receive_wall_ms = int(time.time() * 1_000)
                receive_mono_ns = time.monotonic_ns()
                envelopes.extend(
                    rest_backfill_envelopes(
                        rows,
                        vault=vault,
                        audit=report,
                        receive_wall_ms=receive_wall_ms,
                        receive_mono_ns=receive_mono_ns,
                    )
                )
    return reports, envelopes


def build_copy_vault_bundle(
    raw_root: Path,
    output: Path,
    *,
    collector_version: str,
    reconciliation: Mapping[str, Mapping[str, Any]],
    queue_drops: Mapping[tuple[str, str, str], int],
    selection: Mapping[str, Any],
    collection_run_id: str,
    historical_backfill: Mapping[str, Mapping[str, Any]] | None = None,
) -> dict[str, Any]:
    assets = output / "assets"
    manifests_dir = output / "manifests"
    assets.mkdir(parents=True, exist_ok=True)
    manifests_dir.mkdir(parents=True, exist_ok=True)

    manifests: list[dict[str, Any]] = []
    rejected_admission: list[dict[str, Any]] = []
    for shard in sorted(raw_root.glob("**/shards/*.jsonl.gz")):
        preliminary = build_manifest_from_tick_shard(
            shard,
            collector_version=collector_version,
            reconciliation_status="UNVERIFIED",
        )
        vault = str(preliminary.get("symbol") or "").lower()
        family = str(preliminary.get("family") or "")
        report = reconciliation.get(vault, {})
        if family == "copy_vault_fills":
            preliminary["reconciliation"] = {
                "status": str(report.get("status") or "UNVERIFIED").upper(),
                "live_count": report.get("live_count"),
                "reference_count": report.get("reference_count"),
                "matched_count": report.get("matched_count"),
                "missing_from_live": report.get("missing_from_live"),
                "live_only": report.get("live_only"),
                "audit": dict(report.get("audit") or {}),
            }
        elif family == "copy_vault_snapshot":
            source_id = str(preliminary.get("source") or "")
            history_report = (historical_backfill or {}).get(vault, {})
            if source_id == "hyperliquid_public_userfills_backfill":
                audit = dict(history_report)
                status = (
                    "SNAPSHOT_VERIFIED"
                    if str(audit.get("status") or "").upper() == "COMPLETE"
                    else "UNAVAILABLE"
                )
                preliminary["copy_vault_history"] = audit
                preliminary["reconciliation"] = {
                    "status": status,
                    "method": "bounded_userFillsByTime_pre_selection_v1",
                    "forward_evidence_allowed": False,
                }
            else:
                preliminary["reconciliation"] = {
                    "status": infer_reconciliation_status(preliminary),
                    "method": "websocket_userFills_bootstrap_snapshot_v1",
                    "forward_evidence_allowed": False,
                }
        elif family in {"copy_vault_positions", "copy_vault_selection"}:
            # Immutable public HTTP observation, not an exchange-timestamped
            # trade. Verify local causality and explicit receive-only semantics.
            preliminary["reconciliation"] = {
                "status": infer_reconciliation_status(preliminary),
                "method": "observed_public_http_state_v1",
            }
        else:
            preliminary["reconciliation"] = {"status": "UNVERIFIED"}

        key = (
            str(preliminary["source"]),
            family,
            str(preliminary["symbol"]),
        )
        dropped = int(queue_drops.get(key, 0))
        if dropped:
            integrity = dict(preliminary.get("integrity") or {})
            integrity["gap_count"] = int(integrity.get("gap_count") or 0) + dropped
            preliminary["integrity"] = integrity
            preliminary["collection_queue_drops"] = dropped
        preliminary["collection_run_id"] = str(collection_run_id)
        historical_only = family == "copy_vault_snapshot"
        preliminary["copy_vault_selection"] = {
            "selected_at_ms": selection.get("selected_at_ms"),
            "observation_only": True,
            "forward_only": not historical_only,
            "historical_only": historical_only,
        }
        manifest = finalize_manifest(preliminary)
        if not locally_replay_admissible(manifest):
            rejected_admission.append(admission_rejection(manifest))
            # No unreplayable market payload or trade enters the publish bundle.
            continue

        asset_name = f"{manifest['dataset_id']}.jsonl.gz"
        target = assets / asset_name
        shutil.move(str(shard), target)
        manifest["release_asset"] = asset_name
        manifest["bytes"] = target.stat().st_size
        write_manifest(manifest, manifests_dir / f"{manifest['dataset_id']}.json")
        manifests.append(manifest)

    index = {
        "schema": V2_SCHEMA,
        "repository": V2_REPOSITORY,
        "collector_version": collector_version,
        "collection_run_id": str(collection_run_id),
        "collection_kind": (
            "copy_vault_forward_plus_historical_research"
            if historical_backfill is not None
            else "copy_vault_forward"
        ),
        "selection": dict(selection),
        "historical_backfill": {
            str(vault): dict(report)
            for vault, report in (historical_backfill or {}).items()
        },
        "collection_queue_drops": sum(int(v) for v in queue_drops.values()),
        "source_admission": {
            "mode": "replay_only",
            **summarize_admission_rejections(rejected_admission),
        },
        "shard_count": len(manifests),
        "safe_count": sum(1 for row in manifests if row["quality_status"] == "SAFE"),
        "partial_count": sum(1 for row in manifests if row["quality_status"] == "PARTIAL"),
        "reject_count": sum(1 for row in manifests if row["quality_status"] == "REJECT"),
        "dataset_ids": [row["dataset_id"] for row in manifests],
        "manifests": [f"manifests/{row['dataset_id']}.json" for row in manifests],
        "assets": [f"assets/{row['release_asset']}" for row in manifests],
        "read_only": True,
        "real_execution": False,
    }
    write_manifest(index, output / "BUNDLE_INDEX.json")
    return index


async def collect(
    output: Path,
    *,
    duration_s: float,
    collector_version: str,
    max_vaults: int,
    vault_shard_count: int = 1,
    vault_shard_index: int = 0,
    max_ws_vaults: int = MAX_PRIORITY_WS_VAULTS,
    two_speed: bool = False,
    rotate_bytes: int,
    collection_run_id: str | None = None,
    frozen_selection: Mapping[str, Any] | None = None,
    history_lookback_hours: float = DEFAULT_HISTORY_LOOKBACK_HOURS,
) -> dict[str, Any]:
    if not 0 < float(history_lookback_hours) <= MAX_HISTORY_LOOKBACK_HOURS:
        raise ValueError(
            f"history lookback must be within (0,{MAX_HISTORY_LOOKBACK_HOURS}] hours"
        )
    if frozen_selection is None:
        selected_rows, selection = await asyncio.to_thread(
            discover_vaults,
            max_vaults=max_vaults,
        )
    else:
        selection = dict(frozen_selection)
        raw_rows = selection.get("vaults")
        if not isinstance(raw_rows, list):
            raise ValueError("frozen selection must contain a vaults list")
        selected_rows = [
            dict(row)
            for row in raw_rows
            if isinstance(row, Mapping) and str(row.get("address") or "").strip()
        ][: max(1, int(max_vaults))]
        if not selected_rows:
            raise ValueError("frozen selection contains no usable vaults")

    history_checkpoints_by_vault = {
        str(row.get("address") or "").lower(): row["copy_vault_history_checkpoint"]
        for row in selected_rows
        if isinstance(row.get("copy_vault_history_checkpoint"), Mapping)
    }

    shard_count = max(1, int(vault_shard_count))
    shard_index = int(vault_shard_index)
    if not 0 <= shard_index < shard_count:
        raise ValueError("vault_shard_index must be within vault_shard_count")
    full_count = len(selected_rows)
    if two_speed and (shard_count != 1 or shard_index != 0):
        raise ValueError("two-speed Copy-Vault collection requires one broad universe lane")

    selection_ts_ms = int(selection["selected_at_ms"])
    run_id = str(collection_run_id or "").strip() or (
        f"copy-vault-{str(collector_version)[:12]}-{selection_ts_ms}-"
        f"s{shard_index}of{shard_count}"
    )
    rest_pacer = RestWeightPacer()

    raw_root = output / "raw"
    writer = PartitionedTickDatasetWriter(
        raw_root,
        rotate_bytes=rotate_bytes,
        flush_every=1,
    )
    sink = AsyncTickSink(writer)
    writer_task = asyncio.create_task(sink.run())

    broad_start: dict[str, Any] = {}
    broad_end: dict[str, Any] = {}
    changed_fingerprints = 0

    if two_speed:
        universe_rows = list(selected_rows)
        broad_start = await collect_broad_state(
            universe_rows,
            sink,
            phase="START",
            pacer=rest_pacer,
        )
        priority_rows = select_priority_ws_vaults(
            universe_rows,
            broad_start,
            max_ws_vaults=max_ws_vaults,
            rotation_seed=run_id,
        )
        selected_rows = priority_rows
        broad_digest = hashlib.sha256(
            "\n".join(
                sorted(str(row.get("address") or "").lower() for row in universe_rows)
            ).encode("utf-8")
        ).hexdigest()
        selection = {
            **selection,
            "mode": "two_speed_broad_rest_priority_ws",
            "full_vault_count": full_count,
            "broad_vault_count": full_count,
            "broad_selection_digest": broad_digest,
            "vault_count": len(priority_rows),
            "max_ws_vaults": min(MAX_PRIORITY_WS_VAULTS, int(max_ws_vaults)),
            "vault_shard_count": 1,
            "vault_shard_index": 0,
            "vaults": priority_rows,
        }
    else:
        selected_rows = selected_rows[shard_index::shard_count]
        selection = {
            **selection,
            "mode": "legacy_sharded_ws",
            "full_vault_count": full_count,
            "vault_count": len(selected_rows),
            "vault_shard_count": shard_count,
            "vault_shard_index": shard_index,
            "vaults": selected_rows,
        }

    vaults = [str(row["address"]).lower() for row in selected_rows]
    if not vaults:
        raise RuntimeError("selected Copy-Vault lane is empty")
    validate_user_subscription_budget(vaults)

    for row in selected_rows:
        await _emit_with_backpressure(sink, selection_envelope(row, selection))

    live_ids: dict[str, set[str]] = defaultdict(set)
    live_fill_counts: dict[str, int] = defaultdict(int)
    observation_start_ms: dict[str, int] = {}
    reconnect_counts: dict[str, int] = defaultdict(int)
    l2_request_queue: asyncio.Queue[str] = asyncio.Queue()
    l2_known_coins: set[str] = set()
    l2_state: dict[str, int] = {"frames": 0, "reconnects": 0}
    position_snapshots_start = await collect_position_snapshots(
        vaults,
        sink,
        phase="START",
        pacer=rest_pacer,
    )

    collection_launch_ms = int(time.time() * 1_000)
    groups = [
        vaults[index:index + MAX_SUBSCRIPTIONS_PER_SOCKET]
        for index in range(0, len(vaults), MAX_SUBSCRIPTIONS_PER_SOCKET)
    ]
    tasks = [
        asyncio.create_task(
            _socket_group(
                group,
                sink,
                observation_start_ms=observation_start_ms,
                live_ids=live_ids,
                live_fill_counts=live_fill_counts,
                reconnect_counts=reconnect_counts,
                l2_request_queue=l2_request_queue,
                l2_known_coins=l2_known_coins,
            )
        )
        for group in groups
    ]
    tasks.append(
        asyncio.create_task(
            _dynamic_l2_collector(
                sink,
                l2_request_queue,
                l2_known_coins,
                l2_state,
            )
        )
    )

    requested_duration = max(1.0, float(duration_s))
    if two_speed:
        estimated_end_sweep_s = (
            float(full_count) * BROAD_SWEEP_REQUEST_INTERVAL_S * 1.10
        )
        ws_duration_s = max(
            60.0,
            requested_duration
            - float(broad_start.get("elapsed_s") or 0.0)
            - estimated_end_sweep_s,
        )
    else:
        ws_duration_s = requested_duration

    try:
        await asyncio.sleep(ws_duration_s)
    finally:
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)

    position_snapshots_end = await collect_position_snapshots(
        vaults,
        sink,
        phase="END",
        pacer=rest_pacer,
    )

    if two_speed:
        broad_end = await collect_broad_state(
            universe_rows,
            sink,
            phase="END",
            pacer=rest_pacer,
        )
        start_states = broad_start.get("states")
        end_states = broad_end.get("states")
        if isinstance(start_states, Mapping) and isinstance(end_states, Mapping):
            changed_fingerprints = sum(
                1
                for address in set(start_states) & set(end_states)
                if str(start_states[address].get("position_fingerprint") or "")
                != str(end_states[address].get("position_fingerprint") or "")
            )

    end_ms = int(time.time() * 1_000)
    reports = await reconcile_forward_window(
        vaults,
        start_ms_by_vault=observation_start_ms,
        end_ms=end_ms,
        live_ids=live_ids,
        pacer=rest_pacer,
    )
    historical_reports, historical_envelopes = await collect_historical_backfills(
        vaults,
        selection_ts_ms=selection_ts_ms,
        lookback_hours=history_lookback_hours,
        history_checkpoints=history_checkpoints_by_vault,
        pacer=rest_pacer,
    )
    for envelope in historical_envelopes:
        await _emit_with_backpressure(sink, envelope)
    await sink.close()
    await writer_task
    await asyncio.to_thread(writer.rotate_all)

    index = await asyncio.to_thread(
        build_copy_vault_bundle,
        raw_root,
        output,
        collector_version=collector_version,
        reconciliation=reports,
        queue_drops=sink.drops,
        selection=selection,
        collection_run_id=run_id,
        historical_backfill=historical_reports,
    )
    effective_start_ms = min(
        observation_start_ms.values(),
        default=collection_launch_ms,
    )
    summary = {
        "schema": "alina.copy_vault_cloud_window.v2",
        "collection_run_id": run_id,
        "selection_ts_ms": selection_ts_ms,
        "collection_launch_ts_ms": collection_launch_ms,
        "collection_start_ts_ms": effective_start_ms,
        "vault_observation_start_ts_ms": dict(sorted(observation_start_ms.items())),
        "end_ts_ms": end_ms,
        "duration_s": round((end_ms - effective_start_ms) / 1000.0, 3),
        "requested_duration_s": requested_duration,
        "ws_duration_s": round(ws_duration_s, 3),
        "vault_count": len(vaults),
        "vault_universe_count": selection.get("full_vault_count"),
        "vault_shard_count": selection.get("vault_shard_count"),
        "vault_shard_index": selection.get("vault_shard_index"),
        "copy_vault_mode": selection.get("mode"),
        "priority_ws_vaults": vaults,
        "socket_groups": len(groups),
        "l2_coin_count": len(l2_known_coins),
        "l2_frames": l2_state.get("frames", 0),
        "l2_reconnects": l2_state.get("reconnects", 0),
        "l2_heartbeats": l2_state.get("heartbeats", 0),
        "position_snapshots_start": position_snapshots_start,
        "position_snapshots_end": position_snapshots_end,
        "broad_sweep_start": _compact_sweep_metrics(broad_start),
        "broad_sweep_end": _compact_sweep_metrics(broad_end),
        "broad_position_fingerprints_changed": changed_fingerprints,
        "accepted_frames": sink.accepted,
        "persisted_frames": sink.persisted,
        "backpressure_events": sink.backpressure_events,
        "queue_drops": sum(int(v) for v in sink.drops.values()),
        "live_fill_counts": dict(sorted(live_fill_counts.items())),
        "reconnect_counts": dict(sorted(reconnect_counts.items())),
        "reconciliation": reports,
        "historical_backfill": historical_reports,
        "historical_unique_fill_rows": sum(
            int(report.get("rows") or 0)
            for report in historical_reports.values()
        ),
        "historical_backfill_complete_vaults": sum(
            str(report.get("status") or "").upper() == "COMPLETE"
            for report in historical_reports.values()
        ),
        "history_lookback_hours": float(history_lookback_hours),
        "rest_weight_budget_per_minute": REST_WEIGHT_BUDGET_PER_MINUTE,
        "bundle": {
            "shard_count": index["shard_count"],
            "safe_count": index["safe_count"],
            "partial_count": index["partial_count"],
            "reject_count": index["reject_count"],
        },
        "read_only": True,
        "real_execution": False,
    }
    (output / "collection_summary.json").write_text(
        json.dumps(summary, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return summary

def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", required=True)
    parser.add_argument("--duration-s", type=float, default=300.0)
    parser.add_argument("--collector-version", required=True)
    parser.add_argument("--collection-run-id")
    parser.add_argument("--selection-file")
    parser.add_argument("--max-vaults", type=int, default=100)
    parser.add_argument("--vault-shard-count", type=int, default=1)
    parser.add_argument("--vault-shard-index", type=int, default=0)
    parser.add_argument("--max-ws-vaults", type=int, default=MAX_PRIORITY_WS_VAULTS)
    parser.add_argument("--two-speed", action="store_true")
    parser.add_argument(
        "--history-lookback-hours",
        type=float,
        default=DEFAULT_HISTORY_LOOKBACK_HOURS,
    )
    parser.add_argument("--rotate-mb", type=int, default=64)
    args = parser.parse_args()
    frozen_selection = None
    if args.selection_file:
        payload = json.loads(Path(args.selection_file).read_text(encoding="utf-8"))
        if not isinstance(payload, Mapping):
            raise SystemExit("selection file must contain a JSON object")
        frozen_selection = payload

    summary = asyncio.run(
        collect(
            Path(args.output),
            duration_s=max(1.0, float(args.duration_s)),
            collector_version=str(args.collector_version),
            max_vaults=max(1, int(args.max_vaults)),
            vault_shard_count=max(1, int(args.vault_shard_count)),
            vault_shard_index=int(args.vault_shard_index),
            max_ws_vaults=max(1, min(MAX_PRIORITY_WS_VAULTS, int(args.max_ws_vaults))),
            two_speed=bool(args.two_speed),
            rotate_bytes=max(1, int(args.rotate_mb)) * 1024 * 1024,
            collection_run_id=args.collection_run_id,
            frozen_selection=frozen_selection,
            history_lookback_hours=float(args.history_lookback_hours),
        )
    )
    print(json.dumps(summary, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
