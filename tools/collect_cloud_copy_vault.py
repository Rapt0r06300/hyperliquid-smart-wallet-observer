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
import gzip
import hashlib
import json
import math
import shutil
import sys
import time
import uuid
from collections import defaultdict, deque
from pathlib import Path
from typing import Any, Awaitable, Callable, Mapping, Sequence

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
    infer_reconciliation_status,
    finalize_manifest,
    locally_replay_admissible,
    admission_rejection,
    summarize_admission_rejections,
)
from hl_observer.realtime.feed_quality import FeedEventKind  # noqa: E402

WS_URL = "wss://api.hyperliquid.xyz/ws"
INFO_URL = "https://api.hyperliquid.xyz/info"
MAX_SUBSCRIPTIONS_PER_SOCKET = 5
MAX_UNIQUE_USERS_PER_IP = 10
MAX_RECONCILIATION_REQUESTS_PER_VAULT = 512
RECONCILIATION_PER_VAULT_TIMEOUT_S = 90.0
# clearinghouseState has official weight 2 under a shared 1200 weight/min/IP
# REST budget. 0.14s/request ~= 857 weight/min, leaving safety headroom.
BROAD_SWEEP_REQUEST_INTERVAL_S = 0.14
BROAD_SWEEP_CONCURRENCY = 8
MAX_PRIORITY_WS_VAULTS = 10
PRIORITY_AUDIT_ROTATION_SLOTS = 2
MAX_CHANGED_VAULT_RECONCILIATIONS = 32
MAX_REST_VAULT_RECONCILIATIONS = 128
MAX_HISTORY_BOOTSTRAPS_PER_CAMPAIGN = 2
USERFILLS_WEIGHT_BUDGET_PER_MINUTE = 900
USERFILLS_CAMPAIGN_WEIGHT_BUDGET = 40_000
USERFILLS_CAMPAIGN_REQUEST_BUDGET = 2_048


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


class UserFillsBudgetExhausted(RuntimeError):
    """Campaign-wide public REST request/weight budget was reached."""


class UserFillsRateGate:
    """Keep sequential userFillsByTime calls below the public REST weight limit."""

    def __init__(
        self,
        *,
        weight_budget_per_minute: int = USERFILLS_WEIGHT_BUDGET_PER_MINUTE,
        campaign_weight_budget: int = USERFILLS_CAMPAIGN_WEIGHT_BUDGET,
        campaign_request_budget: int = USERFILLS_CAMPAIGN_REQUEST_BUDGET,
    ) -> None:
        self.weight_budget_per_minute = max(1, int(weight_budget_per_minute))
        self.campaign_weight_budget = max(20, int(campaign_weight_budget))
        self.campaign_request_budget = max(1, int(campaign_request_budget))
        self.weight_used = 0
        self.request_count = 0
        self._next_at = 0.0
        self._lock = asyncio.Lock()

    @property
    def exhausted(self) -> bool:
        return (
            self.request_count >= self.campaign_request_budget
            or self.weight_used + 120 > self.campaign_weight_budget
        )

    async def acquire(self) -> None:
        async with self._lock:
            if (
                self.request_count >= self.campaign_request_budget
                or self.weight_used + 120 > self.campaign_weight_budget
            ):
                raise UserFillsBudgetExhausted("campaign userFillsByTime budget exhausted")
            self.request_count += 1
            self.weight_used += 20
            now = time.monotonic()
            slot = max(now, self._next_at)
            self._next_at = slot + 20 * 60.0 / self.weight_budget_per_minute
        if slot > now:
            await asyncio.sleep(slot - now)

    async def record(self, weight: int) -> None:
        extra_weight = max(0, int(weight) - 20)
        delay = extra_weight * 60.0 / self.weight_budget_per_minute
        async with self._lock:
            self.weight_used += extra_weight
            self._next_at = max(self._next_at, time.monotonic()) + delay


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

                async def send_json(payload: Mapping[str, Any]) -> None:
                    async with send_lock:
                        await socket.send(json.dumps(dict(payload)))

                for coin in sorted(known_coins):
                    await send_json(
                        {
                            "method": "subscribe",
                            "subscription": {"type": "l2Book", "coin": coin},
                        }
                    )
                    subscribed.add(coin)
                    await asyncio.sleep(0.03)

                async def sender() -> None:
                    while True:
                        coin = str(await request_queue.get()).strip().upper()
                        try:
                            if coin and coin not in subscribed:
                                await send_json(
                                    {
                                        "method": "subscribe",
                                        "subscription": {
                                            "type": "l2Book",
                                            "coin": coin,
                                        },
                                    }
                                )
                                subscribed.add(coin)
                        finally:
                            request_queue.task_done()

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
                await gate.wait()
                try:
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
            f"{rotation_seed}|{address}".encode("utf-8")
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

                async def send_json(payload: Mapping[str, Any]) -> None:
                    async with send_lock:
                        await socket.send(json.dumps(dict(payload)))

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
    *,
    rate_gate: UserFillsRateGate | None = None,
) -> list[dict[str, Any]]:
    if rate_gate is not None:
        await rate_gate.acquire()
    try:
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
        if any(not isinstance(row, dict) for row in payload):
            raise ValueError("userFillsByTime returned non-object row")
    except Exception:
        if rate_gate is not None:
            await rate_gate.record(20)
        raise
    if rate_gate is not None:
        await rate_gate.record(20 + math.ceil(len(payload) / 20))
    return payload


async def exact_window_backfill(
    client: httpx.AsyncClient,
    vault: str,
    *,
    start_ms: int,
    end_ms: int,
    min_window_ms: int = 1_000,
    max_requests: int = MAX_RECONCILIATION_REQUESTS_PER_VAULT,
    rate_gate: UserFillsRateGate | None = None,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Adaptive exact-window REST reconciliation using the 2,000 response cap."""
    pending: deque[tuple[int, int]] = deque([(int(start_ms), int(end_ms))])
    accepted: list[dict[str, Any]] = []
    failures: list[dict[str, Any]] = []
    capped_minimum: list[dict[str, Any]] = []
    requests = 0
    splits = 0
    request_budget_exhausted = False
    invalid_source_rows = 0

    while pending:
        if requests >= max(1, int(max_requests)):
            request_budget_exhausted = True
            break
        left, right = pending.popleft()
        requests += 1
        try:
            raw = await _post_userfills(
                client, vault, left, right, rate_gate=rate_gate
            )
        except UserFillsBudgetExhausted:
            requests -= 1
            pending.appendleft((left, right))
            request_budget_exhausted = True
            break
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
                parsed = parser_fills(raw, vault=vault)
                in_window = [
                    row for row in parsed
                    if int(row.get("ts_ms") or -1) >= left
                    and int(row.get("ts_ms") or -1) <= right
                ]
                invalid_source_rows += len(raw) - len(in_window)
                accepted.extend(in_window)
                continue
            middle = left + span // 2
            pending.appendleft((middle + 1, right))
            pending.appendleft((left, middle))
            splits += 1
            continue
        parsed = parser_fills(raw, vault=vault)
        in_window = [
            row for row in parsed
            if int(row.get("ts_ms") or -1) >= left
            and int(row.get("ts_ms") or -1) <= right
        ]
        invalid_source_rows += len(raw) - len(in_window)
        accepted.extend(in_window)

    rows = dedupliquer(accepted)
    return rows, {
        "status": (
            "COMPLETE"
            if not failures and not capped_minimum and not request_budget_exhausted and not invalid_source_rows
            else "PARTIAL"
        ),
        "requested_start_ms": int(start_ms),
        "requested_end_ms": int(end_ms),
        "requests": requests,
        "splits": splits,
        "failed_windows": failures,
        "cap_blocked_windows": capped_minimum,
        "request_budget_exhausted": request_budget_exhausted,
        "invalid_source_rows": invalid_source_rows,
        "pending_windows": len(pending),
        "rows": len(rows),
    }


async def recent_history_backfill(
    client: httpx.AsyncClient,
    vault: str,
    *,
    end_ms: int,
    target_fills: int = 10_000,
    max_requests: int = 128,
    min_window_ms: int = 1_000,
    pending_windows: Sequence[Sequence[int]] | None = None,
    on_window_complete: Callable[[int, int, list[dict[str, Any]]], Awaitable[None]] | None = None,
    rate_gate: UserFillsRateGate | None = None,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Fetch the latest address history in exact windows, resuming unfinished ranges.

    Hyperliquid caps the result at 2,000 fills per response. Capped windows are
    split newest-first; only exact, fully parsed windows are emitted to the sink.
    """
    target = max(1, int(target_fills))
    pending: list[tuple[int, int]] = []
    source_windows = pending_windows or ((1, int(end_ms)),)
    for raw_window in source_windows:
        if not isinstance(raw_window, Sequence) or len(raw_window) != 2:
            continue
        try:
            left, right = int(raw_window[0]), int(raw_window[1])
        except (TypeError, ValueError, OverflowError):
            continue
        if 1 <= left <= right <= int(end_ms):
            pending.append((left, right))
    if not pending:
        pending = [(1, int(end_ms))]

    accepted: list[dict[str, Any]] = []
    completed: list[dict[str, int]] = []
    failed: list[dict[str, Any]] = []
    blocked: list[dict[str, Any]] = []
    requests = 0
    splits = 0
    invalid_source_rows = 0
    request_budget_exhausted = False

    while pending:
        unique_so_far = len(dedupliquer(accepted))
        if unique_so_far >= target:
            break
        if requests >= max(1, int(max_requests)):
            request_budget_exhausted = True
            break
        index = max(range(len(pending)), key=lambda item: (pending[item][1], pending[item][0]))
        left, right = pending.pop(index)
        requests += 1
        try:
            raw = await _post_userfills(
                client, vault, left, right, rate_gate=rate_gate
            )
        except UserFillsBudgetExhausted:
            requests -= 1
            pending.append((left, right))
            request_budget_exhausted = True
            break
        except Exception as exc:
            failed.append({"start_ms": left, "end_ms": right, "error": type(exc).__name__})
            continue

        if len(raw) >= CAP_USERFILLS:
            middle = left + (right - left) // 2
            if right - left < max(2, int(min_window_ms)) or middle < left or middle >= right:
                blocked.append({
                    "start_ms": left,
                    "end_ms": right,
                    "rows": len(raw),
                    "cap": CAP_USERFILLS,
                })
                continue
            pending.extend(((left, middle), (middle + 1, right)))
            splits += 1
            continue

        parsed = parser_fills(raw, vault=vault)
        in_window = [
            row for row in parsed
            if int(row.get("ts_ms") or -1) >= left
            and int(row.get("ts_ms") or -1) <= right
        ]
        invalid = len(raw) - len(in_window)
        invalid_source_rows += invalid
        if invalid:
            failed.append({
                "start_ms": left,
                "end_ms": right,
                "error": "INVALID_OR_OUT_OF_WINDOW_SOURCE_ROWS",
                "invalid_rows": invalid,
            })
            continue

        remaining_target = max(0, target - len(dedupliquer(accepted)))
        selected_rows = sorted(
            in_window,
            key=lambda row: (int(row.get("ts_ms") or 0), canonical_fill_id(row)),
        )[-remaining_target:] if remaining_target else []
        accepted.extend(selected_rows)
        completed.append({"start_ms": left, "end_ms": right, "rows": len(selected_rows)})
        if on_window_complete is not None and selected_rows:
            await on_window_complete(left, right, selected_rows)

    deduped = dedupliquer(accepted)
    visible_ceiling = len(deduped) >= target
    remaining = [] if visible_ceiling else list(pending)
    remaining.extend(
        (int(row["start_ms"]), int(row["end_ms"]))
        for row in failed
        if isinstance(row.get("start_ms"), int) and isinstance(row.get("end_ms"), int)
    )
    remaining.extend(
        (int(row["start_ms"]), int(row["end_ms"]))
        for row in blocked
    )
    remaining = sorted(set(remaining), key=lambda item: (item[1], item[0]), reverse=True)
    exhausted_to_floor = not remaining and not failed and not blocked
    complete = visible_ceiling or exhausted_to_floor
    return dedupliquer(deduped)[-target:], {
        "status": "COMPLETE" if complete else "PARTIAL",
        "requested_start_ms": 1,
        "requested_end_ms": int(end_ms),
        "requests": requests,
        "splits": splits,
        "rows": min(len(deduped), target),
        "visible_fill_ceiling": visible_ceiling,
        "exhausted_to_floor": exhausted_to_floor,
        "request_budget_exhausted": request_budget_exhausted,
        "pending_windows": len(remaining),
        "pending_window_ranges": [[left, right] for left, right in remaining],
        "failed_windows": failed,
        "cap_blocked_windows": blocked,
        "invalid_source_rows": invalid_source_rows,
        "completed_windows": completed,
    }


async def reconcile_forward_window(
    vaults: list[str],
    *,
    start_ms_by_vault: Mapping[str, int],
    end_ms: int,
    live_ids: Mapping[str, set[str]],
    rate_gate: UserFillsRateGate | None = None,
) -> dict[str, dict[str, Any]]:
    reports: dict[str, dict[str, Any]] = {}
    async with httpx.AsyncClient(
        base_url="https://api.hyperliquid.xyz",
        timeout=15.0,
    ) as client:
        for vault in vaults:
            start_ms = start_ms_by_vault.get(vault)
            if rate_gate is not None and rate_gate.exhausted:
                reports[vault] = {
                    "status": "UNAVAILABLE",
                    "live_count": len(live_ids.get(vault, set())),
                    "reference_count": 0,
                    "matched_count": 0,
                    "missing_from_live": None,
                    "live_only": len(live_ids.get(vault, set())),
                    "duplicate_live_keys": 0,
                    "audit": {
                        "status": "PARTIAL",
                        "reason": "CAMPAIGN_USERFILLS_BUDGET_EXHAUSTED",
                        "requested_start_ms": start_ms,
                        "requested_end_ms": int(end_ms),
                        "rows": 0,
                    },
                }
                continue
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
                        rate_gate=rate_gate,
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


def rest_fills_envelope(
    vault: str,
    fills: list[dict[str, Any]],
    *,
    start_ms: int,
    end_ms: int,
    complete: bool,
    historical: bool = False,
) -> TickEnvelope:
    """Build one provenance-bound REST fill envelope for an exact time window."""
    now_ms = int(time.time() * 1_000)
    fill_ids = {canonical_fill_id({**fill, "vault": vault}) for fill in fills}
    return TickEnvelope(
        source_id=(
            "hyperliquid_info_user_fills_by_time_history"
            if historical else "hyperliquid_info_user_fills_by_time"
        ),
        channel="copy_vault_snapshot" if historical else "copy_vault_fills",
        instrument=vault,
        event_kind=(FeedEventKind.SNAPSHOT if historical else FeedEventKind.EVENT),
        raw_payload={
            "request": {
                "type": "userFillsByTime",
                "user": vault,
                "startTime": int(start_ms),
                "endTime": int(end_ms),
                "aggregateByTime": False,
            },
            "fills": fills,
        },
        exchange_ts_ms=max(int(fill["ts_ms"]) for fill in fills),
        received_ts_ms=now_ms,
        local_monotonic_ns=time.monotonic_ns(),
        connection_id=f"copy-vault-rest-{uuid.uuid4().hex}",
        sequence=None,
        provenance={
            "url": INFO_URL,
            "network": "mainnet",
            "access": "read_only",
            "transport": "https",
            "endpoint": "/info",
            "request_type": "userFillsByTime",
            "authenticated": False,
            "selection_causal": True,
            "timestamp_semantics": "exchange_event_time",
            "window_reconciliation_complete": bool(complete),
            "history_bootstrap": bool(historical),
        },
        parsed_summary={
            "event_count": len(fill_ids),
            "first_fill_ts_ms": min(int(fill["ts_ms"]) for fill in fills),
            "last_fill_ts_ms": max(int(fill["ts_ms"]) for fill in fills),
            "exact_window": bool(complete),
            "history_bootstrap": bool(historical),
            "data_gate_ready": False,
        },
    )


def changed_vault_addresses(
    rows: list[Mapping[str, Any]],
    start_states: Mapping[str, Any],
    end_states: Mapping[str, Any],
    *,
    excluded_vaults: set[str],
) -> tuple[list[dict[str, Any]], dict[str, int]]:
    """Return causal broad-state changes and exact observation-coverage counts."""
    universe = {
        str(row.get("address") or "").strip().lower(): dict(row)
        for row in rows
        if isinstance(row, Mapping) and str(row.get("address") or "").strip()
    }
    start = {str(key).lower(): value for key, value in start_states.items()}
    end = {str(key).lower(): value for key, value in end_states.items()}
    comparable = set(universe) & set(start) & set(end)
    missing = set(universe) - comparable
    changed: list[dict[str, Any]] = []
    for address in comparable:
        if address in {str(item).lower() for item in excluded_vaults}:
            continue
        left = start[address]
        right = end[address]
        if not isinstance(left, Mapping) or not isinstance(right, Mapping):
            missing.add(address)
            continue
        if str(left.get("position_fingerprint") or "") == str(
            right.get("position_fingerprint") or ""
        ):
            continue
        row = universe[address]
        row["broad_n_positions"] = int(right.get("n_positions") or 0)
        row["broad_expo_brute_usd"] = float(right.get("expo_brute_usd") or 0.0)
        changed.append(row)
    changed.sort(
        key=lambda row: (
            -int(row.get("broad_n_positions") or 0),
            -float(row.get("broad_expo_brute_usd") or 0.0),
            -float(row.get("tvl_usd") or 0.0),
            str(row.get("address") or "").lower(),
        )
    )
    return changed, {
        "universe_wallets": len(universe),
        "comparable_wallets": len(comparable) - len(missing & comparable),
        "missing_state_wallets": len(missing),
        "missing_state_vaults": sorted(missing),
        "changed_wallets": len(changed),
    }


async def collect_changed_vault_fills(
    rows: list[Mapping[str, Any]],
    start_states: Mapping[str, Any],
    end_states: Mapping[str, Any],
    sink: Any,
    *,
    start_ms: int,
    end_ms: int,
    excluded_vaults: set[str],
    fill_checkpoints: Mapping[str, Mapping[str, Any]] | None = None,
    rate_gate: UserFillsRateGate | None = None,
    max_vaults: int = MAX_CHANGED_VAULT_RECONCILIATIONS,
) -> dict[str, Any]:
    """Backfill changed broad-sweep wallets and preserve coverage failures."""
    changed, coverage = changed_vault_addresses(
        rows, start_states, end_states, excluded_vaults=excluded_vaults
    )
    limit = max(0, int(max_vaults))
    selected = changed[:limit]
    reports: dict[str, dict[str, Any]] = {}
    checkpoint_updates: dict[str, dict[str, Any]] = {}
    fills_collected = 0
    async with httpx.AsyncClient(
        base_url="https://api.hyperliquid.xyz", timeout=15.0
    ) as client:
        for row in selected:
            if rate_gate is not None and rate_gate.exhausted:
                break
            vault = str(row["address"]).lower()
            checkpoint = (fill_checkpoints or {}).get(vault, {})
            pending_start = checkpoint.get("forward_pending_start_ms") if isinstance(checkpoint, Mapping) else None
            previous_end = checkpoint.get("last_forward_end_ms") if isinstance(checkpoint, Mapping) else None
            try:
                if pending_start is not None:
                    wallet_start_ms = int(pending_start)
                else:
                    wallet_start_ms = max(int(start_ms), int(previous_end) + 1) if previous_end is not None else int(start_ms)
            except (TypeError, ValueError, OverflowError):
                wallet_start_ms = int(start_ms)
            if wallet_start_ms >= int(end_ms):
                reports[vault] = {
                    "status": "ALREADY_COVERED",
                    "method": "exact_userFillsByTime_window",
                    "live_count": 0,
                    "reference_count": 0,
                    "matched_count": 0,
                    "missing_from_live": 0,
                    "live_only": 0,
                    "audit": {
                        "status": "COMPLETE",
                        "requested_start_ms": wallet_start_ms,
                        "requested_end_ms": int(end_ms),
                        "requests": 0,
                        "rows": 0,
                    },
                }
                continue
            try:
                fills, audit = await asyncio.wait_for(
                    exact_window_backfill(
                        client,
                        vault,
                        start_ms=wallet_start_ms,
                        end_ms=int(end_ms),
                        rate_gate=rate_gate,
                    ),
                    timeout=RECONCILIATION_PER_VAULT_TIMEOUT_S,
                )
            except TimeoutError:
                fills = []
                audit = {
                    "status": "PARTIAL",
                    "reason": "REFERENCE_TIMEOUT",
                    "requested_start_ms": wallet_start_ms,
                    "requested_end_ms": int(end_ms),
                    "rows": 0,
                }
            complete = str(audit.get("status") or "").upper() == "COMPLETE"
            fill_ids = {canonical_fill_id({**fill, "vault": vault}) for fill in fills}
            if fills:
                envelope = rest_fills_envelope(
                    vault,
                    fills,
                    start_ms=wallet_start_ms,
                    end_ms=int(end_ms),
                    complete=complete,
                )
                await _emit_with_backpressure(sink, envelope)
                fills_collected += len(fill_ids)
            reports[vault] = {
                "status": "SOURCE_CONTINUITY_VERIFIED" if complete else "UNAVAILABLE",
                "method": "exact_userFillsByTime_window",
                "live_count": len(fill_ids),
                "reference_count": len(fill_ids),
                "matched_count": len(fill_ids) if complete else 0,
                "missing_from_live": 0 if complete else None,
                "live_only": 0,
                "audit": audit,
            }
            updated_checkpoint = dict(checkpoint) if isinstance(checkpoint, Mapping) else {}
            updated_checkpoint["checkpoint_schema"] = "alina.copy_vault_fill_checkpoint.v1"
            updated_checkpoint["last_forward_attempt_ms"] = int(time.time() * 1_000)
            if complete:
                updated_checkpoint.update({
                    "last_forward_start_ms": wallet_start_ms,
                    "last_forward_end_ms": int(end_ms),
                    "last_forward_status": "SOURCE_CONTINUITY_VERIFIED",
                    "forward_failure_count": 0,
                })
                updated_checkpoint.pop("forward_pending_start_ms", None)
                updated_checkpoint.pop("forward_retry_after_ms", None)
            else:
                updated_checkpoint.setdefault("forward_pending_start_ms", wallet_start_ms)
                updated_checkpoint["last_forward_status"] = "PARTIAL"
                failures = min(16, int(updated_checkpoint.get("forward_failure_count") or 0) + 1)
                updated_checkpoint["forward_failure_count"] = failures
                updated_checkpoint["forward_retry_after_ms"] = (
                    int(time.time() * 1_000)
                    + min(24 * 60 * 60_000, 60 * 60_000 * (2 ** min(5, failures - 1)))
                )
            checkpoint_updates[vault] = updated_checkpoint
    attempted = set(reports)
    unattempted = [str(row["address"]).lower() for row in selected if str(row["address"]).lower() not in attempted]
    incomplete = sum(
        1 for report in reports.values()
        if report["status"] not in {"SOURCE_CONTINUITY_VERIFIED", "ALREADY_COVERED"}
    )
    deferred = max(0, len(changed) - len(selected)) + len(unattempted)
    missing_state = int(coverage["missing_state_wallets"])
    return {
        "status": "COMPLETE" if not incomplete and not deferred and not missing_state else "PARTIAL",
        **coverage,
        "reconciled_wallets": len(selected),
        "deferred_wallets": deferred,
        "deferred_vaults": (
            [str(row["address"]).lower() for row in changed[len(selected):]]
            + unattempted
        ),
        "incomplete_wallets": incomplete,
        "incomplete_vaults": sorted(
            vault for vault, report in reports.items()
            if report["status"] != "SOURCE_CONTINUITY_VERIFIED"
        ),
        "fills_collected": fills_collected,
        "start_ts_ms": int(start_ms),
        "end_ts_ms": int(end_ms),
        "wallet_reports": reports,
        "vault_checkpoints": checkpoint_updates,
    }


async def collect_checkpointed_vault_fills(
    candidates: Sequence[Any],
    fill_checkpoints: Mapping[str, Mapping[str, Any]],
    sink: Any,
    *,
    start_ms: int,
    end_ms: int,
    excluded_vaults: set[str],
    rate_gate: UserFillsRateGate,
    max_vaults: int = MAX_REST_VAULT_RECONCILIATIONS,
) -> dict[str, Any]:
    """Poll a rotating, checkpointed REST slice outside the ten live WS users."""
    excluded = {str(value).strip().lower() for value in excluded_vaults}
    all_candidates: list[str] = []
    seen: set[str] = set()
    for item in candidates:
        raw_address = item.get("address") if isinstance(item, Mapping) else item
        vault = str(raw_address or "").strip().lower()
        if not vault or vault in seen or vault in excluded:
            continue
        seen.add(vault)
        all_candidates.append(vault)
    selected = all_candidates[:max(1, int(max_vaults))]

    reports: dict[str, dict[str, Any]] = {}
    updates: dict[str, dict[str, Any]] = {}
    fills_collected = 0
    async with httpx.AsyncClient(
        base_url="https://api.hyperliquid.xyz", timeout=15.0
    ) as client:
        for vault in selected:
            if rate_gate.exhausted:
                break
            previous = fill_checkpoints.get(vault, {})
            checkpoint = dict(previous) if isinstance(previous, Mapping) else {}
            checkpoint["checkpoint_schema"] = "alina.copy_vault_fill_checkpoint.v1"
            try:
                pending_start = checkpoint.get("forward_pending_start_ms")
                previous_end = checkpoint.get("last_forward_end_ms")
                if pending_start is not None:
                    window_start = int(pending_start)
                else:
                    window_start = (
                        max(int(start_ms), int(previous_end) + 1)
                        if previous_end is not None else int(start_ms)
                    )
            except (TypeError, ValueError, OverflowError):
                window_start = int(start_ms)
            now_attempt_ms = int(time.time() * 1_000)
            if window_start >= int(end_ms):
                reports[vault] = {
                    "status": "ALREADY_COVERED",
                    "method": "exact_userFillsByTime_window",
                    "audit": {
                        "status": "COMPLETE",
                        "requested_start_ms": window_start,
                        "requested_end_ms": int(end_ms),
                        "requests": 0,
                        "rows": 0,
                    },
                }
                continue
            try:
                fills, audit = await asyncio.wait_for(
                    exact_window_backfill(
                        client,
                        vault,
                        start_ms=window_start,
                        end_ms=int(end_ms),
                        rate_gate=rate_gate,
                    ),
                    timeout=RECONCILIATION_PER_VAULT_TIMEOUT_S,
                )
            except TimeoutError:
                fills = []
                audit = {
                    "status": "PARTIAL",
                    "reason": "REFERENCE_TIMEOUT",
                    "requested_start_ms": window_start,
                    "requested_end_ms": int(end_ms),
                    "rows": 0,
                }
            complete = str(audit.get("status") or "").upper() == "COMPLETE"
            if complete and fills:
                await _emit_with_backpressure(
                    sink,
                    rest_fills_envelope(
                        vault,
                        fills,
                        start_ms=window_start,
                        end_ms=int(end_ms),
                        complete=True,
                    ),
                )
                fills_collected += len({canonical_fill_id({**row, "vault": vault}) for row in fills})
            checkpoint["last_forward_attempt_ms"] = now_attempt_ms
            if complete:
                checkpoint.update({
                    "last_forward_start_ms": window_start,
                    "last_forward_end_ms": int(end_ms),
                    "last_forward_status": "SOURCE_CONTINUITY_VERIFIED",
                    "forward_failure_count": 0,
                })
                checkpoint.pop("forward_pending_start_ms", None)
                checkpoint.pop("forward_retry_after_ms", None)
                status = "SOURCE_CONTINUITY_VERIFIED"
            else:
                checkpoint.setdefault("forward_pending_start_ms", window_start)
                checkpoint["last_forward_status"] = "PARTIAL"
                failures = min(16, int(checkpoint.get("forward_failure_count") or 0) + 1)
                checkpoint["forward_failure_count"] = failures
                checkpoint["forward_retry_after_ms"] = (
                    int(time.time() * 1_000)
                    + min(24 * 60 * 60_000, 60 * 60_000 * (2 ** min(5, failures - 1)))
                )
                status = "UNAVAILABLE"
            updates[vault] = checkpoint
            reports[vault] = {
                "status": status,
                "method": "checkpointed_exact_userFillsByTime_window",
                "live_count": 0,
                "reference_count": int(audit.get("rows") or 0),
                "matched_count": 0,
                "missing_from_live": None,
                "live_only": 0,
                "audit": audit,
            }
    return {
        "status": "COMPLETE" if all(
            row.get("status") in {"SOURCE_CONTINUITY_VERIFIED", "ALREADY_COVERED"}
            for row in reports.values()
        ) and len(selected) == len(all_candidates) and len(reports) == len(selected) else "PARTIAL",
        "selected_wallets": len(selected),
        "deferred_wallets": (
            max(0, len(all_candidates) - len(selected))
            + max(0, len(selected) - len(reports))
        ),
        "fills_collected": fills_collected,
        "start_ts_ms": int(start_ms),
        "end_ts_ms": int(end_ms),
        "wallet_reports": reports,
        "vault_checkpoints": updates,
    }


async def bootstrap_vault_history(
    vaults: Sequence[str],
    fill_checkpoints: Mapping[str, Mapping[str, Any]],
    sink: Any,
    *,
    end_ms: int,
    rate_gate: UserFillsRateGate,
    target_fills: int = 10_000,
    max_requests_per_vault: int = 128,
) -> dict[str, Any]:
    """Incrementally recover bounded public history for frozen Copy-Vault leaders."""
    reports: dict[str, dict[str, Any]] = {}
    updates: dict[str, dict[str, Any]] = {}
    fills_collected = 0
    requested_vaults = [
        str(vault).strip().lower()
        for vault in vaults[:MAX_HISTORY_BOOTSTRAPS_PER_CAMPAIGN]
        if str(vault).strip()
    ]
    async with httpx.AsyncClient(
        base_url="https://api.hyperliquid.xyz", timeout=15.0
    ) as client:
        for raw_vault in requested_vaults:
            if rate_gate.exhausted:
                break
            vault = str(raw_vault).strip().lower()
            if not vault:
                continue
            previous = fill_checkpoints.get(vault, {})
            checkpoint = dict(previous) if isinstance(previous, Mapping) else {}
            checkpoint["checkpoint_schema"] = "alina.copy_vault_fill_checkpoint.v1"
            if checkpoint.get("history_complete") is True:
                continue
            try:
                prior_count = max(0, int(checkpoint.get("history_fill_count") or 0))
                prior_end_raw = checkpoint.get("history_coverage_end_ms")
                prior_end = int(prior_end_raw) if prior_end_raw is not None else None
                pending = [
                    [int(pair[0]), int(pair[1])]
                    for pair in checkpoint.get("history_pending_windows", [])
                    if isinstance(pair, Sequence) and len(pair) == 2
                ]
            except (TypeError, ValueError, OverflowError):
                prior_count, prior_end, pending = 0, None, []
            if prior_end is None:
                pending = pending or [[1, int(end_ms)]]
            elif prior_end < int(end_ms):
                pending.append([prior_end + 1, int(end_ms)])
            if not pending:
                pending = [[1, int(end_ms)]]

            async def emit_window(left: int, right: int, fills: list[dict[str, Any]]) -> None:
                await _emit_with_backpressure(
                    sink,
                    rest_fills_envelope(
                        vault,
                        fills,
                        start_ms=left,
                        end_ms=right,
                        complete=True,
                        historical=True,
                    ),
                )

            try:
                fills, audit = await recent_history_backfill(
                    client,
                    vault,
                    end_ms=int(end_ms),
                    target_fills=max(1, int(target_fills) - prior_count),
                    max_requests=max_requests_per_vault,
                    pending_windows=pending,
                    on_window_complete=emit_window,
                    rate_gate=rate_gate,
                )
            except Exception as exc:
                fills = []
                audit = {
                    "status": "PARTIAL",
                    "reason": type(exc).__name__,
                    "pending_window_ranges": pending,
                    "rows": 0,
                }
            complete = str(audit.get("status") or "").upper() == "COMPLETE"
            added = len({canonical_fill_id({**row, "vault": vault}) for row in fills})
            fills_collected += added
            checkpoint.update({
                "history_complete": complete,
                "history_status": "COMPLETE" if complete else "PARTIAL",
                "history_fill_count": min(int(target_fills), prior_count + added),
                "history_coverage_end_ms": int(end_ms),
                "history_pending_windows": audit.get("pending_window_ranges") or [],
                "history_last_attempt_ms": int(time.time() * 1_000),
                "history_last_audit": {
                    key: value for key, value in audit.items()
                    if key not in {"completed_windows", "failed_windows", "cap_blocked_windows"}
                },
            })
            if audit.get("cap_blocked_windows"):
                checkpoint["history_retry_after_ms"] = int(time.time() * 1_000) + 7 * 86_400_000
                checkpoint["history_failure_count"] = min(
                    16, int(checkpoint.get("history_failure_count") or 0) + 1
                )
            elif audit.get("failed_windows") or audit.get("reason"):
                failures = min(
                    16, int(checkpoint.get("history_failure_count") or 0) + 1
                )
                checkpoint["history_failure_count"] = failures
                checkpoint["history_retry_after_ms"] = (
                    int(time.time() * 1_000)
                    + min(24 * 60 * 60_000, 60 * 60_000 * (2 ** min(5, failures - 1)))
                )
            else:
                checkpoint.pop("history_retry_after_ms", None)
                checkpoint["history_failure_count"] = 0
            updates[vault] = checkpoint
            reports[vault] = {
                "status": "SOURCE_CONTINUITY_VERIFIED" if complete else "UNAVAILABLE",
                "history_scan_status": "COMPLETE" if complete else "PARTIAL",
                "fills_collected": added,
                "history_fill_count": checkpoint["history_fill_count"],
                "audit": audit,
            }
    return {
        "status": "COMPLETE" if (
            len(reports) == len(requested_vaults)
            and all(row.get("history_scan_status") == "COMPLETE" for row in reports.values())
        ) else "PARTIAL",
        "wallet_count": len(reports),
        "deferred_wallets": max(0, len(requested_vaults) - len(reports)),
        "fills_collected": fills_collected,
        "wallet_reports": reports,
        "vault_checkpoints": updates,
        "history_scope": "latest address history, bounded by public API visibility and request budget",
    }


def build_copy_vault_bundle(
    raw_root: Path,
    output: Path,
    *,
    collector_version: str,
    reconciliation: Mapping[str, Mapping[str, Any]],
    queue_drops: Mapping[tuple[str, str, str], int],
    selection: Mapping[str, Any],
    collection_run_id: str,
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
        provenance = preliminary.get("provenance") or {}
        historical_window = (
            preliminary.get("source")
            in {
                "hyperliquid_info_user_fills_by_time_history",
                "hyperliquid_info_user_fills_by_time",
            }
            and provenance.get("request_type") == "userFillsByTime"
            and provenance.get("window_reconciliation_complete") is True
            and provenance.get("history_bootstrap") is True
        )
        if family == "copy_vault_fills" and historical_window:
            preliminary["reconciliation"] = {
                "status": "SOURCE_CONTINUITY_VERIFIED",
                "method": "exact_userFillsByTime_history_window_legacy_family",
            }
        elif family == "copy_vault_fills":
            preliminary["reconciliation"] = {
                "status": str(report.get("status") or "UNVERIFIED").upper(),
                "method": report.get("method"),
                "live_count": report.get("live_count"),
                "reference_count": report.get("reference_count"),
                "matched_count": report.get("matched_count"),
                "missing_from_live": report.get("missing_from_live"),
                "live_only": report.get("live_only"),
                "audit": report.get("audit"),
            }
        elif (
            family == "copy_vault_snapshot"
            and preliminary.get("source")
            == "hyperliquid_info_user_fills_by_time_history"
            and historical_window
        ):
            # Each history shard is one exact REST window. The overall wallet
            # bootstrap may remain partial; only the verified window itself is
            # admitted as historical research evidence, never as forward proof.
            preliminary["reconciliation"] = {
                "status": "SOURCE_CONTINUITY_VERIFIED",
                "method": "exact_userFillsByTime_history_window",
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
        preliminary["copy_vault_selection"] = {
            "selected_at_ms": selection.get("selected_at_ms"),
            "observation_only": True,
            "forward_only": str(preliminary.get("source") or "")
            != "hyperliquid_info_user_fills_by_time_history",
            "historical_bootstrap": str(preliminary.get("source") or "")
            == "hyperliquid_info_user_fills_by_time_history",
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
        "collection_kind": "copy_vault_forward",
        "selection": dict(selection),
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
) -> dict[str, Any]:
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
    campaign_window_start_ms = int(time.time() * 1_000)

    if two_speed:
        universe_rows = list(selected_rows)
        broad_start = await collect_broad_state(
            universe_rows,
            sink,
            phase="START",
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
    raw_checkpoints = selection.get("fill_checkpoints")
    fill_checkpoints = {
        str(address).strip().lower(): dict(value)
        for address, value in raw_checkpoints.items()
        if isinstance(raw_checkpoints, Mapping)
        and isinstance(value, Mapping)
        and str(address).strip()
    } if isinstance(raw_checkpoints, Mapping) else {}
    forward_candidates_raw = selection.get("forward_reconcile_vaults")
    forward_candidates = (
        [str(value).strip().lower() for value in forward_candidates_raw if str(value).strip()]
        if isinstance(forward_candidates_raw, list) else []
    )
    history_bootstrap_vaults_raw = selection.get("history_bootstrap_vaults")
    history_bootstrap_vaults = (
        [str(value).strip().lower() for value in history_bootstrap_vaults_raw if str(value).strip()]
        if isinstance(history_bootstrap_vaults_raw, list) else []
    )

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
    )

    if two_speed:
        broad_end = await collect_broad_state(
            universe_rows,
            sink,
            phase="END",
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
    userfills_rate_gate = UserFillsRateGate()
    targeted_reconciliation: dict[str, Any] = {
        "status": "NOT_APPLICABLE",
        "changed_wallets": 0,
        "reconciled_wallets": 0,
        "deferred_wallets": 0,
        "incomplete_wallets": 0,
        "fills_collected": 0,
        "wallet_reports": {},
    }
    reports = await reconcile_forward_window(
        vaults,
        start_ms_by_vault=observation_start_ms,
        end_ms=end_ms,
        live_ids=live_ids,
        rate_gate=userfills_rate_gate,
    )
    checkpoint_updates: dict[str, dict[str, Any]] = {}
    for vault, report in reports.items():
        if report.get("status") == "MATCHED":
            checkpoint = dict(fill_checkpoints.get(vault, {}))
            audit = report.get("audit") if isinstance(report.get("audit"), Mapping) else {}
            checkpoint.update({
                "checkpoint_schema": "alina.copy_vault_fill_checkpoint.v1",
                "last_forward_start_ms": int(audit.get("requested_start_ms") or 0),
                "last_forward_end_ms": int(end_ms),
                "last_forward_status": "SOURCE_CONTINUITY_VERIFIED",
                "last_forward_attempt_ms": int(time.time() * 1_000),
                "forward_failure_count": 0,
            })
            checkpoint.pop("forward_pending_start_ms", None)
            checkpoint.pop("forward_retry_after_ms", None)
            checkpoint_updates[vault] = checkpoint
        elif report.get("status") in {"UNAVAILABLE", "PARTIAL", "MISMATCH"}:
            audit = report.get("audit") if isinstance(report.get("audit"), Mapping) else {}
            requested_start = audit.get("requested_start_ms")
            if isinstance(requested_start, int) and requested_start > 0:
                checkpoint = dict(fill_checkpoints.get(vault, {}))
                checkpoint["checkpoint_schema"] = "alina.copy_vault_fill_checkpoint.v1"
                checkpoint.setdefault("forward_pending_start_ms", requested_start)
                checkpoint["last_forward_attempt_ms"] = int(time.time() * 1_000)
                checkpoint["last_forward_status"] = "PARTIAL"
                failures = min(16, int(checkpoint.get("forward_failure_count") or 0) + 1)
                checkpoint["forward_failure_count"] = failures
                checkpoint["forward_retry_after_ms"] = (
                    int(time.time() * 1_000)
                    + min(24 * 60 * 60_000, 60 * 60_000 * (2 ** min(5, failures - 1)))
                )
                checkpoint_updates[vault] = checkpoint
    forward_poll = await collect_checkpointed_vault_fills(
        forward_candidates,
        {**fill_checkpoints, **checkpoint_updates},
        sink,
        start_ms=campaign_window_start_ms,
        end_ms=end_ms,
        excluded_vaults=set(vaults),
        rate_gate=userfills_rate_gate,
    )
    reports.update(forward_poll.get("wallet_reports") or {})
    checkpoint_updates.update({
        str(address).lower(): dict(value)
        for address, value in (forward_poll.get("vault_checkpoints") or {}).items()
        if isinstance(value, Mapping)
    })
    if two_speed:
        start_states = broad_start.get("states")
        end_states = broad_end.get("states")
        if isinstance(start_states, Mapping) and isinstance(end_states, Mapping):
            targeted_reconciliation = await collect_changed_vault_fills(
                universe_rows,
                start_states,
                end_states,
                sink,
                start_ms=campaign_window_start_ms,
                end_ms=end_ms,
                excluded_vaults=set(vaults) | set(forward_poll.get("wallet_reports") or {}),
                fill_checkpoints={**fill_checkpoints, **checkpoint_updates},
                rate_gate=userfills_rate_gate,
            )
        else:
            targeted_reconciliation = {
                **targeted_reconciliation,
                "status": "UNAVAILABLE",
                "reason": "BROAD_SWEEP_STATE_MISSING",
                "missing_state_wallets": full_count,
            }
    targeted_wallet_reports = targeted_reconciliation.get("wallet_reports") or {}
    reports.update(targeted_wallet_reports)
    checkpoint_updates.update({
        str(address).lower(): dict(value)
        for address, value in (targeted_reconciliation.get("vault_checkpoints") or {}).items()
        if isinstance(value, Mapping)
    })
    history_bootstrap = await bootstrap_vault_history(
        history_bootstrap_vaults,
        {**fill_checkpoints, **checkpoint_updates},
        sink,
        end_ms=end_ms,
        rate_gate=userfills_rate_gate,
    )
    reports.update(history_bootstrap.get("wallet_reports") or {})
    checkpoint_updates.update({
        str(address).lower(): dict(value)
        for address, value in (history_bootstrap.get("vault_checkpoints") or {}).items()
        if isinstance(value, Mapping)
    })
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
        "targeted_change_reconciliation": {
            key: value
            for key, value in targeted_reconciliation.items()
            if key != "wallet_reports"
        },
        "forward_rest_reconciliation": {
            key: value
            for key, value in forward_poll.items()
            if key not in {"wallet_reports", "vault_checkpoints"}
        },
        "historical_bootstrap": {
            key: value
            for key, value in history_bootstrap.items()
            if key not in {"wallet_reports", "vault_checkpoints"}
        },
        "accepted_frames": sink.accepted,
        "persisted_frames": sink.persisted,
        "backpressure_events": sink.backpressure_events,
        "queue_drops": sum(int(v) for v in sink.drops.values()),
        "live_fill_counts": dict(sorted(live_fill_counts.items())),
        "reconnect_counts": dict(sorted(reconnect_counts.items())),
        "reconciliation": reports,
        "vault_checkpoints": checkpoint_updates,
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
        )
    )
    print(json.dumps(summary, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
