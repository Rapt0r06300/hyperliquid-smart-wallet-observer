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
import json
import shutil
import sys
import time
import uuid
from collections import defaultdict, deque
from pathlib import Path
from typing import Any, Mapping

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
    finalize_manifest,
)
from hl_observer.realtime.feed_quality import FeedEventKind  # noqa: E402

WS_URL = "wss://api.hyperliquid.xyz/ws"
INFO_URL = "https://api.hyperliquid.xyz/info"
MAX_SUBSCRIPTIONS_PER_SOCKET = 5


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
        try:
            self.queue.put_nowait(envelope)
            self.accepted += 1
        except asyncio.QueueFull:
            self.drops[self.key(envelope)] += 1

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
                for coin in sorted(known_coins):
                    await socket.send(
                        json.dumps(
                            {
                                "method": "subscribe",
                                "subscription": {"type": "l2Book", "coin": coin},
                            }
                        )
                    )
                    subscribed.add(coin)
                    await asyncio.sleep(0.03)

                async def sender() -> None:
                    while True:
                        coin = str(await request_queue.get()).strip().upper()
                        try:
                            if coin and coin not in subscribed:
                                await socket.send(
                                    json.dumps(
                                        {
                                            "method": "subscribe",
                                            "subscription": {
                                                "type": "l2Book",
                                                "coin": coin,
                                            },
                                        }
                                    )
                                )
                                subscribed.add(coin)
                        finally:
                            request_queue.task_done()

                sender_task = asyncio.create_task(sender())
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
                            sink.emit(envelope)
                            state["frames"] = state.get("frames", 0) + 1
                finally:
                    sender_task.cancel()
                    await asyncio.gather(sender_task, return_exceptions=True)
        except asyncio.CancelledError:
            raise
        except Exception:
            state["reconnects"] = state.get("reconnects", 0) + 1
            await asyncio.sleep(min(30.0, 2.0 ** min(attempt, 5)))
            attempt += 1


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
                sink.emit(envelope)
                count += 1
    return count


async def _socket_group(
    vaults: list[str],
    sink: AsyncTickSink,
    *,
    selection_ts_ms: int,
    live_ids: dict[str, set[str]],
    live_fill_counts: dict[str, int],
    reconnect_counts: dict[str, int],
    l2_request_queue: asyncio.Queue[str],
    l2_known_coins: set[str],
) -> None:
    attempt = 0
    group_key = "-".join(vault[:8] for vault in vaults)
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
                for vault in vaults:
                    await socket.send(
                        json.dumps(
                            {
                                "method": "subscribe",
                                "subscription": {
                                    "type": "userFills",
                                    "user": vault,
                                },
                            }
                        )
                    )
                    await asyncio.sleep(0.15)
                attempt = 0
                async for raw_text in socket:
                    mono = time.monotonic_ns()
                    wall = int(time.time() * 1_000)
                    try:
                        message = json.loads(raw_text)
                    except (TypeError, ValueError):
                        continue
                    if not isinstance(message, Mapping):
                        continue
                    if message.get("channel") == "subscriptionResponse":
                        continue
                    data = message.get("data")
                    user = str(data.get("user") or "").lower() if isinstance(data, Mapping) else ""
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
                    sink.emit(envelope)

                    # Pre-warm execution L2 from every observed coin, including the
                    # initial userFills snapshot. Snapshot fills never count as forward
                    # signals; they are used only to decide what public market data to
                    # observe before a future leader action.
                    for fill in fills:
                        coin = str(fill.get("coin") or "").strip().upper()
                        if coin and coin not in l2_known_coins:
                            l2_known_coins.add(coin)
                            l2_request_queue.put_nowait(coin)

                    # Only forward, non-snapshot fills observed after selection count
                    # toward causal reconciliation.
                    if envelope.channel != "copy_vault_fills":
                        continue
                    for fill in fills:
                        try:
                            ts_ms = int(fill.get("ts_ms") or 0)
                        except (TypeError, ValueError, OverflowError):
                            continue
                        if ts_ms < int(selection_ts_ms):
                            continue
                        live_ids[vault].add(canonical_fill_id(fill))
                        live_fill_counts[vault] += 1
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
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Adaptive exact-window REST reconciliation using the 2,000 response cap."""
    pending: deque[tuple[int, int]] = deque([(int(start_ms), int(end_ms))])
    accepted: list[dict[str, Any]] = []
    failures: list[dict[str, Any]] = []
    capped_minimum: list[dict[str, Any]] = []
    requests = 0
    splits = 0

    while pending:
        left, right = pending.popleft()
        requests += 1
        try:
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
                accepted.extend(parser_fills(raw, vault=vault))
                continue
            middle = left + max(1, span // 2)
            pending.appendleft((middle, right))
            pending.appendleft((left, middle))
            splits += 1
            continue
        accepted.extend(parser_fills(raw, vault=vault))

    rows = dedupliquer(accepted)
    return rows, {
        "status": "COMPLETE" if not failures and not capped_minimum else "PARTIAL",
        "requested_start_ms": int(start_ms),
        "requested_end_ms": int(end_ms),
        "requests": requests,
        "splits": splits,
        "failed_windows": failures,
        "cap_blocked_windows": capped_minimum,
        "rows": len(rows),
    }


async def reconcile_forward_window(
    vaults: list[str],
    *,
    start_ms: int,
    end_ms: int,
    live_ids: Mapping[str, set[str]],
) -> dict[str, dict[str, Any]]:
    reports: dict[str, dict[str, Any]] = {}
    async with httpx.AsyncClient(
        base_url="https://api.hyperliquid.xyz",
        timeout=15.0,
    ) as client:
        for vault in vaults:
            rows, audit = await exact_window_backfill(
                client,
                vault,
                start_ms=start_ms,
                end_ms=end_ms,
            )
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


def build_copy_vault_bundle(
    raw_root: Path,
    output: Path,
    *,
    collector_version: str,
    reconciliation: Mapping[str, Mapping[str, Any]],
    queue_drops: Mapping[tuple[str, str, str], int],
    selection: Mapping[str, Any],
) -> dict[str, Any]:
    assets = output / "assets"
    manifests_dir = output / "manifests"
    assets.mkdir(parents=True, exist_ok=True)
    manifests_dir.mkdir(parents=True, exist_ok=True)

    manifests: list[dict[str, Any]] = []
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
        preliminary["copy_vault_selection"] = {
            "selected_at_ms": selection.get("selected_at_ms"),
            "observation_only": True,
            "forward_only": True,
        }
        manifest = finalize_manifest(preliminary)

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
        "collection_kind": "copy_vault_forward",
        "selection": dict(selection),
        "collection_queue_drops": sum(int(v) for v in queue_drops.values()),
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
    rotate_bytes: int,
) -> dict[str, Any]:
    selected_rows, selection = await asyncio.to_thread(
        discover_vaults,
        max_vaults=max_vaults,
    )
    shard_count = max(1, int(vault_shard_count))
    shard_index = int(vault_shard_index)
    if not 0 <= shard_index < shard_count:
        raise ValueError("vault_shard_index must be within vault_shard_count")
    full_count = len(selected_rows)
    selected_rows = selected_rows[shard_index::shard_count]
    selection = {
        **selection,
        "full_vault_count": full_count,
        "vault_count": len(selected_rows),
        "vault_shard_count": shard_count,
        "vault_shard_index": shard_index,
        "vaults": selected_rows,
    }
    vaults = [str(row["address"]).lower() for row in selected_rows]
    if not vaults:
        raise RuntimeError("selected Copy-Vault shard is empty")
    selection_ts_ms = int(selection["selected_at_ms"])

    raw_root = output / "raw"
    writer = PartitionedTickDatasetWriter(
        raw_root,
        rotate_bytes=rotate_bytes,
        flush_every=1,
    )
    sink = AsyncTickSink(writer)
    writer_task = asyncio.create_task(sink.run())

    for row in selected_rows:
        sink.emit(selection_envelope(row, selection))

    live_ids: dict[str, set[str]] = defaultdict(set)
    live_fill_counts: dict[str, int] = defaultdict(int)
    reconnect_counts: dict[str, int] = defaultdict(int)
    l2_request_queue: asyncio.Queue[str] = asyncio.Queue()
    l2_known_coins: set[str] = set()
    l2_state: dict[str, int] = {"frames": 0, "reconnects": 0}
    position_snapshots_start = await collect_position_snapshots(
        vaults,
        sink,
        phase="START",
    )
    groups = [
        vaults[index:index + MAX_SUBSCRIPTIONS_PER_SOCKET]
        for index in range(0, len(vaults), MAX_SUBSCRIPTIONS_PER_SOCKET)
    ]
    tasks = [
        asyncio.create_task(
            _socket_group(
                group,
                sink,
                selection_ts_ms=selection_ts_ms,
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

    try:
        await asyncio.sleep(max(1.0, float(duration_s)))
    finally:
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)

    position_snapshots_end = await collect_position_snapshots(
        vaults,
        sink,
        phase="END",
    )
    end_ms = int(time.time() * 1_000)
    reports = await reconcile_forward_window(
        vaults,
        start_ms=selection_ts_ms,
        end_ms=end_ms,
        live_ids=live_ids,
    )
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
    )
    summary = {
        "schema": "alina.copy_vault_cloud_window.v1",
        "selection_ts_ms": selection_ts_ms,
        "end_ts_ms": end_ms,
        "duration_s": round((end_ms - selection_ts_ms) / 1000.0, 3),
        "vault_count": len(vaults),
        "vault_universe_count": selection.get("full_vault_count"),
        "vault_shard_count": selection.get("vault_shard_count"),
        "vault_shard_index": selection.get("vault_shard_index"),
        "socket_groups": len(groups),
        "l2_coin_count": len(l2_known_coins),
        "l2_frames": l2_state.get("frames", 0),
        "l2_reconnects": l2_state.get("reconnects", 0),
        "position_snapshots_start": position_snapshots_start,
        "position_snapshots_end": position_snapshots_end,
        "accepted_frames": sink.accepted,
        "persisted_frames": sink.persisted,
        "queue_drops": sum(int(v) for v in sink.drops.values()),
        "live_fill_counts": dict(sorted(live_fill_counts.items())),
        "reconnect_counts": dict(sorted(reconnect_counts.items())),
        "reconciliation": reports,
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
    parser.add_argument("--max-vaults", type=int, default=100)
    parser.add_argument("--vault-shard-count", type=int, default=1)
    parser.add_argument("--vault-shard-index", type=int, default=0)
    parser.add_argument("--rotate-mb", type=int, default=64)
    args = parser.parse_args()
    summary = asyncio.run(
        collect(
            Path(args.output),
            duration_s=max(1.0, float(args.duration_s)),
            collector_version=str(args.collector_version),
            max_vaults=max(1, min(int(args.max_vaults), CV.MAX_VAULTS_PUBLICS)),
            vault_shard_count=max(1, int(args.vault_shard_count)),
            vault_shard_index=int(args.vault_shard_index),
            rotate_bytes=max(1, int(args.rotate_mb)) * 1024 * 1024,
        )
    )
    print(json.dumps(summary, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
