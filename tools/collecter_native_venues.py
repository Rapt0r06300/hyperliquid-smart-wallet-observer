"""Collecteur persistant multi-venue public/read-only.

Ce runner NE crée PAS une seconde architecture de marché. Il branche simplement
`NativeVenueCoordinator` au stockage replayable déjà existant (`TickDatasetWriter`)
et au superviseur canonique des collecteurs.

Sources natives : Bybit, OKX, Gate.io, Bitget.
Hyperliquid + Binance restent propriétaires de `tools/collecter_bbo.py`.

Sécurité : endpoints publics uniquement, aucune clé, aucune signature, aucun ordre.
"""
# The repository paths must be bootstrapped before importing its local packages.
# ruff: noqa: E402
from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import time
from collections.abc import Callable, Mapping
from copy import copy
from pathlib import Path
from typing import Any

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE / "src"))
sys.path.insert(0, str(RACINE / "tools"))

import heartbeat_collecteur as HB

from hl_observer.collection.bounded_tick_queue import BoundedTickEnvelopeQueue
from hl_observer.collection.native_funding_history import (
    fetch_bybit_funding_settlements,
    fetch_okx_funding_settlements,
)
from hl_observer.collection.native_venue_coordinator import NativeVenueCoordinator
from hl_observer.collection.native_venue_market import NativeMarketSnapshot
from hl_observer.collection.partitioned_tick_dataset import PartitionedTickDatasetWriter
from hl_observer.collection.tick_dataset import TickEnvelope, _raw_text
from hl_observer.datasets.v2_pipeline import build_bundle
from hl_observer.realtime.feed_quality import FeedEventKind

HEARTBEAT = Path("runtime") / "data" / "native_venues_heartbeat.json"
TICK_DATASET_DIR = Path("runtime") / "data" / "market_ticks"
MARQUEUR = Path("runtime") / "data" / "lanceur_session_marqueur.txt"
QUEUE_MAX = 100_000
QUEUE_MAX_BYTES = 256 * 1024 * 1024
QUEUE_BATCH_MAX_BYTES = 32 * 1024 * 1024
MANIFEST_FLUSH_RECORDS = 128
STREAM_NAME = "native_venues_market_ticks"
VENUES = ("bybit", "okx", "gate", "bitget")
DEFAULT_UNIVERSE_REFRESH_S = 900.0
HEARTBEAT_WRITE_INTERVAL_S = 5.0


def _atomic_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(dict(payload), ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp, path)


def _prepare_queue_envelope(envelope: TickEnvelope) -> TickEnvelope:
    """Compact JSON payloads once before queue sizing and durable writing.

    TickDatasetWriter stores ``raw_payload`` as the canonical JSON text. Keeping
    the original mapping in this bounded queue would serialize it once for the
    byte estimate and again when writing. A shallow envelope copy preserves the
    caller's object while making the writer consume the already canonical text.
    """
    raw_payload = envelope.raw_payload
    if isinstance(raw_payload, (str, bytes)):
        return envelope
    compacted = copy(envelope)
    compacted.raw_payload = _raw_text(raw_payload)
    return compacted


def snapshot_summary(
    snapshot: NativeMarketSnapshot,
    *,
    clock_domain_id: str | None = None,
) -> dict[str, Any]:
    """Résumé normalisé persistant, sans donnée d'exécution."""
    bid_size = snapshot.bids[0].size if snapshot.bids else None
    ask_size = snapshot.asks[0].size if snapshot.asks else None
    return {
        "venue": snapshot.venue,
        "coin": snapshot.coin,
        "clock_domain_id": str(clock_domain_id or "") or None,
        "exchange_symbol": snapshot.exchange_symbol,
        "bid": snapshot.bid,
        "ask": snapshot.ask,
        "mid": snapshot.mid,
        "spread_bps": snapshot.spread_bps,
        "bid_size": bid_size,
        "ask_size": ask_size,
        "bids": [[level.price, level.size] for level in snapshot.bids],
        "asks": [[level.price, level.size] for level in snapshot.asks],
        "depth_levels_bid": len(snapshot.bids),
        "depth_levels_ask": len(snapshot.asks),
        "quality": snapshot.quality,
        "reason": snapshot.reason,
        "last": snapshot.last,
        "mark": snapshot.mark,
        "index": snapshot.index,
        "volume_24h": snapshot.volume_24h,
        "open_interest": snapshot.open_interest,
        "funding_rate": snapshot.funding_rate,
        "funding_interval_hours": snapshot.funding_interval_hours,
        "sequence": snapshot.sequence,
        "update_id": snapshot.update_id,
        "connection_id": snapshot.connection_id,
        "receive_mono_ns": snapshot.receive_mono_ns,
        "transport_rtt_ms": snapshot.transport_rtt_ms,
        "clock_offset_ms": snapshot.clock_offset_ms,
        "gap_count": snapshot.gap_count,
        "duplicate_count": snapshot.duplicate_count,
        "regression_count": snapshot.regression_count,
        "exchange_ts_ms": snapshot.exchange_ts_ms,
        "receive_ts_ms": snapshot.receive_ts_ms,
        "read_only": True,
        "real_execution": False,
    }


def envelope_from_snapshot(
    snapshot: NativeMarketSnapshot,
    raw_payload: Mapping[str, object],
    *,
    monotonic_ns: int | None = None,
    clock_domain_id: str | None = None,
) -> TickEnvelope:
    return TickEnvelope(
        source_id=f"{snapshot.venue}_public_readonly",
        channel="native_market",
        instrument=snapshot.coin,
        event_kind=FeedEventKind.SNAPSHOT,
        raw_payload=dict(raw_payload),
        exchange_ts_ms=snapshot.exchange_ts_ms or None,
        received_ts_ms=snapshot.receive_ts_ms,
        local_monotonic_ns=(
            monotonic_ns
            if monotonic_ns is not None
            else snapshot.receive_mono_ns
            if snapshot.receive_mono_ns is not None
            else time.monotonic_ns()
        ),
        connection_id=snapshot.connection_id,
        sequence=snapshot.sequence,
        gap_count=snapshot.gap_count,
        provenance={
            "venue": snapshot.venue,
            "access": "public_read_only",
            "transport": "websocket",
            "authenticated": False,
            "collector": "native_venues",
            "clock_domain_id": str(clock_domain_id or "") or None,
        },
        parsed_summary=snapshot_summary(
            snapshot,
            clock_domain_id=clock_domain_id,
        ),
    )


class RecordingNativeVenueCoordinator(NativeVenueCoordinator):
    """Même coordinateur, avec un sink local après normalisation."""

    def __init__(
        self,
        *args: Any,
        on_snapshot: Callable[[TickEnvelope], None],
        clock_domain_id: str,
        **kwargs: Any,
    ) -> None:
        super().__init__(*args, **kwargs)
        self._on_snapshot = on_snapshot
        self._clock_domain_id = str(clock_domain_id)

    def _record(
        self,
        snapshot: NativeMarketSnapshot | None,
        payload: Mapping[str, object],
    ) -> NativeMarketSnapshot | None:
        if snapshot is not None:
            self._on_snapshot(
                envelope_from_snapshot(
                    snapshot,
                    payload,
                    clock_domain_id=self._clock_domain_id,
                )
            )
        return snapshot

    def ingest_bybit(self, payload: Mapping[str, object], **kwargs: Any) -> NativeMarketSnapshot | None:
        snapshot = super().ingest_bybit(payload, **kwargs)
        # Preserve both the immutable raw frame and a normalized full-L2 snapshot.
        # They are different replay channels, not duplicate economic evidence.
        return self._record(snapshot, payload)

    def ingest_okx(self, payload: Mapping[str, object], **kwargs: Any) -> NativeMarketSnapshot | None:
        snapshot = super().ingest_okx(payload, **kwargs)
        return self._record(snapshot, payload)

    def ingest_gate(self, payload: Mapping[str, object], **kwargs: Any) -> NativeMarketSnapshot | None:
        return self._record(super().ingest_gate(payload, **kwargs), payload)

    def ingest_bitget(self, payload: Mapping[str, object], **kwargs: Any) -> NativeMarketSnapshot | None:
        return self._record(super().ingest_bitget(payload, **kwargs), payload)


async def _run(
    root: Path,
    *,
    max_symbols: int,
    stale_after_ms: int,
    duration_s: float,
    universe_refresh_s: float = DEFAULT_UNIVERSE_REFRESH_S,
    enabled_venues: tuple[str, ...] = VENUES,
    symbol_shard_count: int = 1,
    symbol_shard_index: int = 0,
    rotate_bytes: int = 512 * 1024 * 1024,
) -> int:
    queue = BoundedTickEnvelopeQueue(
        max_items=QUEUE_MAX,
        max_estimated_bytes=QUEUE_MAX_BYTES,
    )
    dropped = 0
    dropped_by_venue: dict[str, int] = {}
    dropped_by_channel: dict[str, dict[str, int]] = {}
    invalid_receive_timestamp_count = 0
    invalid_receive_timestamp_by_venue: dict[str, int] = {}
    oversized_dropped = 0
    written = 0
    enabled_venues = tuple(venue for venue in VENUES if venue in set(enabled_venues))
    if not enabled_venues:
        raise ValueError("enabled_venues must contain at least one supported venue")
    reconnects = {venue: 0 for venue in enabled_venues}
    last_event_ms = {venue: 0 for venue in enabled_venues}
    last_exchange_ts = {venue: 0 for venue in enabled_venues}
    channel_counts: dict[str, dict[str, int]] = {
        venue: {} for venue in enabled_venues
    }
    canonical_last_written = 0
    canonical_last_beat_ns = 0
    heartbeat_last_write_ns = 0
    required = tuple(venue for venue in ("bybit", "okx") if venue in enabled_venues)
    started = time.time()
    collection_start_wall_ms = int(started * 1000)
    github_run_id = str(os.getenv("GITHUB_RUN_ID") or "").strip()
    collection_run_id = (
        str(os.getenv("ALINA_COLLECTION_RUN_ID") or "").strip()
        or (f"github-{github_run_id}" if github_run_id else "")
        or f"native-{collection_start_wall_ms}"
    )
    universe_refreshes = 0
    universe_changes = 0
    marker0 = (root / MARQUEUR).read_text(encoding="utf-8").strip() if (root / MARQUEUR).exists() else ""

    def enqueue(envelope: TickEnvelope) -> bool:
        nonlocal dropped, oversized_dropped, invalid_receive_timestamp_count

        source_id = str(getattr(envelope, "source_id", "") or "")
        venue = source_id.split("_", 1)[0].lower() or "unknown"
        channel = str(getattr(envelope, "channel", "") or "unknown")
        try:
            received_ts_ms = int(envelope.received_ts_ms)
        except (AttributeError, TypeError, ValueError, OverflowError):
            received_ts_ms = 0
        if received_ts_ms <= 0:
            invalid_receive_timestamp_count += 1
            invalid_receive_timestamp_by_venue[venue] = (
                invalid_receive_timestamp_by_venue.get(venue, 0) + 1
            )
            return False

        def mark_dropped(_envelope: TickEnvelope) -> None:
            nonlocal dropped
            dropped += 1
            venue = str(getattr(_envelope, "source_id", "") or "").split(
                "_", 1
            )[0].lower() or "unknown"
            channel = str(getattr(_envelope, "channel", "") or "unknown")
            dropped_by_venue[venue] = dropped_by_venue.get(venue, 0) + 1
            venue_channels = dropped_by_channel.setdefault(venue, {})
            venue_channels[channel] = venue_channels.get(channel, 0) + 1

        accepted = queue.append(_prepare_queue_envelope(envelope), on_drop=mark_dropped)
        if not accepted:
            oversized_dropped += 1
            return False
        if venue in channel_counts and channel != "unknown":
            venue_counts = channel_counts[venue]
            venue_counts[channel] = int(venue_counts.get(channel, 0)) + 1
        if venue in last_event_ms:
            last_event_ms[venue] = max(last_event_ms[venue], received_ts_ms)
            if envelope.exchange_ts_ms is not None:
                last_exchange_ts[venue] = max(
                    int(last_exchange_ts[venue]),
                    int(envelope.exchange_ts_ms),
                )
        return True
    writer = PartitionedTickDatasetWriter(
        root / TICK_DATASET_DIR,
        rotate_bytes=max(8 * 1024 * 1024, int(rotate_bytes)),
        # Each JSONL batch is still fsynced. The mutable partition manifest is
        # metadata, so update it every 128 records; rotation always seals it.
        flush_every=MANIFEST_FLUSH_RECORDS,
    )
    write_batch_task: asyncio.Task[int] | None = None
    write_batch_started_ns: int | None = None
    write_batch_records = 0
    last_dataset_stats = writer.stats(include_partitions=False)

    class QueueTickWriter:
        def append(self, envelope: TickEnvelope) -> int:
            return int(enqueue(envelope))

    queue_tick_writer = QueueTickWriter()

    clock_domain_id = (
        f"{collection_run_id}:native-shard-{symbol_shard_index}:"
        f"{collection_start_wall_ms}"
    )
    coordinator = RecordingNativeVenueCoordinator(
        on_snapshot=enqueue,
        clock_domain_id=clock_domain_id,
        tick_writer=queue_tick_writer,
        stale_after_ms=stale_after_ms,
        max_symbols_per_venue=max_symbols,
        symbol_shard_count=symbol_shard_count,
        symbol_shard_index=symbol_shard_index,
        ccxt_snapshot_path=root / "data" / "ccxt_universe.json",
    )

    def enqueue_bybit_instrument_metadata() -> int:
        rows = getattr(coordinator.bybit_client, "last_instrument_metadata", ())
        active = set(coordinator.symbols_for("bybit"))
        if not rows or not active:
            return 0
        received_ts_ms = int(time.time() * 1_000)
        receive_mono_ns = time.monotonic_ns()
        emitted = 0
        for raw in rows:
            if not isinstance(raw, Mapping):
                continue
            symbol = str(raw.get("symbol") or "").upper()
            if symbol not in active:
                continue
            price_filter = raw.get("priceFilter")
            lot_filter = raw.get("lotSizeFilter")
            price = dict(price_filter) if isinstance(price_filter, Mapping) else {}
            lot = dict(lot_filter) if isinstance(lot_filter, Mapping) else {}
            accepted = enqueue(
                TickEnvelope(
                    source_id="bybit_public_rest",
                    channel="instrument_metadata",
                    instrument=symbol,
                    event_kind=FeedEventKind.SNAPSHOT,
                    raw_payload=dict(raw),
                    exchange_ts_ms=None,
                    received_ts_ms=received_ts_ms,
                    local_monotonic_ns=receive_mono_ns,
                    connection_id=None,
                    sequence=None,
                    provenance={
                        "url": f"{coordinator.bybit_client.rest_base_url}/v5/market/instruments-info",
                        "network": "mainnet",
                        "access": "read_only",
                        "transport": "https",
                        "authenticated": False,
                        "collector": "native_venues",
                    },
                    parsed_summary={
                        "status": raw.get("status"),
                        "contract_type": raw.get("contractType"),
                        "tick_size": price.get("tickSize"),
                        "qty_step": lot.get("qtyStep"),
                        "min_order_qty": lot.get("minOrderQty"),
                        "min_notional_value": lot.get("minNotionalValue"),
                        "funding_interval_minutes": raw.get("fundingInterval"),
                        "data_gate_ready": False,
                    },
                )
            )
            emitted += int(accepted)
        return emitted
    registry = await asyncio.to_thread(coordinator.discover)
    enqueue_bybit_instrument_metadata()
    await asyncio.to_thread(coordinator.refresh_clock_sync)
    counts = {venue: len(coordinator.symbols_for(venue)) for venue in enabled_venues}
    funding_symbols_seen: dict[str, set[str]] = {
        venue: set(coordinator.symbols_for(venue))
        for venue in enabled_venues
        if venue in {"bybit", "okx"}
    }
    funding_history_counts = {"bybit": 0, "okx": 0}
    funding_history_errors = {"bybit": "", "okx": ""}
    if not any(counts.values()):
        print("[native-venues] aucun marche decouvert sur Bybit/OKX/Gate/Bitget", flush=True)
        return 2

    def symbols_snapshot() -> dict[str, tuple[str, ...]]:
        return {
            venue: tuple(coordinator.symbols_for(venue))
            for venue in enabled_venues
        }

    async def venue_loop(venue: str) -> None:
        method = getattr(coordinator, f"run_{venue}")
        while True:
            try:
                await method()
                # Bybit/OKX periodically rotate their public socket. The
                # dedicated universe supervisor owns REST rediscovery and targeted
                # restarts, avoiding duplicate discovery bursts at the same cadence.
                await asyncio.sleep(1.0)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                reconnects[venue] += 1
                print(
                    f"[native-venues] {venue} reconnect #{reconnects[venue]}: "
                    f"{type(exc).__name__}: {exc}",
                    flush=True,
                )
                await asyncio.sleep(min(30.0, 2.0 ** min(reconnects[venue], 4)))

    managed_tasks: set[asyncio.Task[Any]] = set()
    venue_tasks: dict[str, asyncio.Task[Any]] = {}

    def start_venue_task(venue: str) -> None:
        task = asyncio.create_task(venue_loop(venue))
        venue_tasks[venue] = task
        managed_tasks.add(task)

    for venue in enabled_venues:
        start_venue_task(venue)

    if counts.get("bybit") or counts.get("okx"):
        clock_task = asyncio.create_task(coordinator.run_clock_sync())
        managed_tasks.add(clock_task)

    async def universe_refresh_loop() -> None:
        nonlocal registry, counts, universe_refreshes, universe_changes
        if universe_refresh_s <= 0:
            return
        while True:
            await asyncio.sleep(universe_refresh_s)
            before = symbols_snapshot()
            refreshed = await asyncio.to_thread(coordinator.discover)
            enqueue_bybit_instrument_metadata()
            after = symbols_snapshot()
            registry = refreshed
            counts = {venue: len(after[venue]) for venue in enabled_venues}
            for venue in funding_symbols_seen:
                funding_symbols_seen[venue].update(after.get(venue, ()))
            universe_refreshes += 1
            changed = [venue for venue in enabled_venues if before[venue] != after[venue]]
            if not changed:
                continue
            universe_changes += len(changed)
            print(
                f"[native-venues] univers change: {','.join(changed)} -> redemarrage cible",
                flush=True,
            )
            for venue in changed:
                old_task = venue_tasks.get(venue)
                if old_task is not None:
                    old_task.cancel()
                    await asyncio.gather(old_task, return_exceptions=True)
                start_venue_task(venue)

    refresh_task = asyncio.create_task(universe_refresh_loop())
    managed_tasks.add(refresh_task)
    try:
        while True:
            await asyncio.sleep(0.25)
            if write_batch_task is not None and write_batch_task.done():
                completed_write = write_batch_task
                write_batch_task = None
                write_batch_started_ns = None
                write_batch_records = 0
                written += int(completed_write.result())
                last_dataset_stats = writer.stats(include_partitions=False)
            if write_batch_task is None and queue:
                batch = queue.pop_batch(
                    max_items=5_000,
                    max_estimated_bytes=QUEUE_BATCH_MAX_BYTES,
                )
                write_batch_records = len(batch)
                write_batch_started_ns = time.monotonic_ns()
                write_batch_task = asyncio.create_task(
                    asyncio.to_thread(writer.append_batch, batch)
                )

            now = time.time()
            marker_path = root / MARQUEUR
            marker = marker_path.read_text(encoding="utf-8").strip() if marker_path.exists() else marker0
            stop_reason = ""
            if marker != marker0:
                stop_reason = "SESSION_MARKER_CHANGED"
            elif duration_s > 0 and now - started >= duration_s:
                stop_reason = "DURATION_REACHED"

            now_ms = int(now * 1000)
            now_mono_ns = time.monotonic_ns()
            if now_mono_ns - canonical_last_beat_ns >= 2_000_000_000:
                required_ready = all(
                    counts.get(venue, 0) > 0 and last_event_ms.get(venue, 0) > 0
                    for venue in required
                )
                stale_limit_ms = max(10_000, int(stale_after_ms) * 4)
                required_stale = any(
                    last_event_ms.get(venue, 0) > 0
                    and now_ms - int(last_event_ms[venue]) > stale_limit_ms
                    for venue in required
                )
                HB.battre(
                    root,
                    "native-venues",
                    pid=os.getpid(),
                    n_ecrites=max(0, int(written) - int(canonical_last_written)),
                    dernier_exchange_ts=max(last_exchange_ts.values()) or None,
                    souscription_ack=required_ready,
                    note="Bybit+OKX native public market data",
                    metriques={
                        "gaps_critiques": int(dropped),
                        "reconnects": int(sum(reconnects.values())),
                        "stale": bool(required_stale),
                    },
                )
                canonical_last_written = int(written)
                canonical_last_beat_ns = now_mono_ns
            heartbeat_due = (
                heartbeat_last_write_ns == 0
                or now_mono_ns - heartbeat_last_write_ns
                >= int(HEARTBEAT_WRITE_INTERVAL_S * 1_000_000_000)
                or bool(stop_reason)
            )
            if heartbeat_due:
                health = coordinator.health(now_ms=now_ms)
                _atomic_json(
                    root / HEARTBEAT,
                    {
                        "schema_version": "alina.native_venues_heartbeat.v1",
                        "pid": os.getpid(),
                        "collection_run_id": collection_run_id,
                        "ts": now,
                        "duration_s": round(now - started, 3),
                        "state": "STOPPING" if stop_reason else "RUNNING",
                        "stop_reason": stop_reason or None,
                        "discovered_registry_coins": len(registry),
                        "subscribed_symbols": {
                            venue: len(coordinator.symbols_for(venue))
                            for venue in VENUES
                        },
                        "initial_subscribed_symbols": counts,
                        "universe_refreshes": universe_refreshes,
                        "universe_changes": universe_changes,
                        "universe_refresh_interval_s": universe_refresh_s,
                        "records_written": written,
                        "queue_depth": len(queue),
                        "queue_estimated_bytes": queue.estimated_bytes,
                        "queue_estimated_byte_limit": queue.max_estimated_bytes,
                        "queue_drops": dropped,
                        "queue_drops_by_venue": dict(sorted(dropped_by_venue.items())),
                        "queue_drops_by_channel": {
                            venue: dict(sorted(channels.items()))
                            for venue, channels in sorted(dropped_by_channel.items())
                        },
                        "invalid_receive_timestamp_count": invalid_receive_timestamp_count,
                        "invalid_receive_timestamp_by_venue": dict(
                            sorted(invalid_receive_timestamp_by_venue.items())
                        ),
                        "queue_oversized_drops": oversized_dropped,
                        "writer_batch_pending": write_batch_task is not None,
                        "writer_batch_records": write_batch_records,
                        "writer_batch_age_s": (
                            round(
                                max(0, now_mono_ns - write_batch_started_ns)
                                / 1_000_000_000,
                                3,
                            )
                            if write_batch_started_ns is not None
                            else 0.0
                        ),
                        "reconnects": reconnects,
                        "last_event_ms": last_event_ms,
                        "last_exchange_ts": last_exchange_ts,
                        "channel_counts": {
                            venue: dict(sorted(channel_counts.get(venue, {}).items()))
                            for venue in enabled_venues
                        },
                        "required_venues": list(required),
                        "required_venues_ready": all(
                            counts.get(venue, 0) > 0
                            and last_event_ms.get(venue, 0) > 0
                            for venue in required
                        ),
                        "coordinator_health": health,
                        # Do not inspect mutable writer dictionaries while the
                        # disk thread may be creating partition writers.
                        "dataset": last_dataset_stats,
                        "read_only": True,
                        "real_execution": False,
                    },
                )
                heartbeat_last_write_ns = now_mono_ns
            if stop_reason:
                break
    finally:
        current_tasks = list(managed_tasks)
        for task in current_tasks:
            if not task.done():
                task.cancel()
        await asyncio.gather(*current_tasks, return_exceptions=True)
        if write_batch_task is not None:
            written += int(await asyncio.shield(write_batch_task))
            write_batch_task = None
            write_batch_started_ns = None
            write_batch_records = 0
            last_dataset_stats = writer.stats(include_partitions=False)
        funding_end_wall_ms = int(time.time() * 1000)
        if "bybit" in enabled_venues:
            try:
                rows = await fetch_bybit_funding_settlements(
                    funding_symbols_seen.get("bybit", set()),
                    start_ms=collection_start_wall_ms,
                    end_ms=funding_end_wall_ms,
                )
                for envelope in rows:
                    enqueue(envelope)
                funding_history_counts["bybit"] = len(rows)
            except Exception as exc:
                funding_history_errors["bybit"] = f"{type(exc).__name__}: {exc}"[:500]
        if "okx" in enabled_venues:
            try:
                rows = await fetch_okx_funding_settlements(
                    funding_symbols_seen.get("okx", set()),
                    start_ms=collection_start_wall_ms,
                    end_ms=funding_end_wall_ms,
                )
                for envelope in rows:
                    enqueue(envelope)
                funding_history_counts["okx"] = len(rows)
            except Exception as exc:
                funding_history_errors["okx"] = f"{type(exc).__name__}: {exc}"[:500]
        while queue:
            batch = queue.pop_batch(
                max_items=5_000,
                max_estimated_bytes=QUEUE_BATCH_MAX_BYTES,
            )
            written += writer.append_batch(batch)
        await asyncio.to_thread(writer.rotate_all)
        collector_version = (
            str(os.getenv("ALINA_COLLECTOR_VERSION") or "").strip()
            or str(os.getenv("GITHUB_SHA") or "").strip()
            or "unversioned"
        )
        bundle = await asyncio.to_thread(
            build_bundle,
            root / TICK_DATASET_DIR,
            root / "runtime" / "data" / "dataset_v2_bundle" / "native_venues",
            collector_version=collector_version,
            collection_queue_drops=dropped,
            collection_run_id=collection_run_id,
            compact_target_bytes=64 * 1024 * 1024,
            replay_admission_only=True,
        )
        final_health = coordinator.health(now_ms=int(time.time() * 1000))
        final = {
            "schema_version": "alina.native_venues_heartbeat.v1",
            "pid": os.getpid(),
            "collection_run_id": collection_run_id,
            "ts": time.time(),
            "duration_s": round(time.time() - started, 3),
            "state": "STOPPED",
            "discovered_registry_coins": len(registry),
            "subscribed_symbols": {
                venue: len(coordinator.symbols_for(venue))
                for venue in VENUES
            },
            "initial_subscribed_symbols": counts,
            "universe_refreshes": universe_refreshes,
            "universe_changes": universe_changes,
            "universe_refresh_interval_s": universe_refresh_s,
            "records_written": written,
            "queue_depth": len(queue),
            "queue_estimated_bytes": queue.estimated_bytes,
            "queue_estimated_byte_limit": queue.max_estimated_bytes,
            "queue_drops": dropped,
            "queue_drops_by_venue": dict(sorted(dropped_by_venue.items())),
            "queue_drops_by_channel": {
                venue: dict(sorted(channels.items()))
                for venue, channels in sorted(dropped_by_channel.items())
            },
            "invalid_receive_timestamp_count": invalid_receive_timestamp_count,
            "invalid_receive_timestamp_by_venue": dict(
                sorted(invalid_receive_timestamp_by_venue.items())
            ),
            "queue_oversized_drops": oversized_dropped,
            "writer_batch_pending": False,
            "writer_batch_records": 0,
            "writer_batch_age_s": 0.0,
            "reconnects": reconnects,
            "last_event_ms": last_event_ms,
            "last_exchange_ts": last_exchange_ts,
            "channel_counts": {
                venue: dict(sorted(channel_counts.get(venue, {}).items()))
                for venue in enabled_venues
            },
            "funding_history_counts": funding_history_counts,
            "funding_history_errors": funding_history_errors,
            "required_venues": [
                venue for venue in ("bybit", "okx") if venue in enabled_venues
            ],
            "required_venues_ready": all(
                counts.get(venue, 0) > 0 and last_event_ms.get(venue, 0) > 0
                for venue in ("bybit", "okx") if venue in enabled_venues
            ),
            "coordinator_health": final_health,
            "dataset": writer.stats(include_partitions=False),
            "dataset_v2_bundle": bundle,
            "read_only": True,
            "real_execution": False,
        }
        _atomic_json(root / HEARTBEAT, final)
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Collecte native persistante Bybit/OKX/Gate/Bitget, publique et read-only."
    )
    parser.add_argument("--root", default=str(RACINE))
    parser.add_argument("--max-symbols", type=int, default=50)
    parser.add_argument(
        "--venues",
        default=",".join(VENUES),
        help="Comma-separated subset of bybit,okx,gate,bitget.",
    )
    parser.add_argument(
        "--symbol-shard-count",
        type=int,
        default=1,
        help="Split the ranked max-symbol universe into N deterministic lanes.",
    )
    parser.add_argument(
        "--symbol-shard-index",
        type=int,
        default=0,
        help="Zero-based lane index within --symbol-shard-count.",
    )
    parser.add_argument("--stale-after-ms", type=int, default=1_500)
    parser.add_argument(
        "--rotate-mb",
        type=int,
        default=512,
        help="Taille cible des shards immuables; borne 8..1536 MiB.",
    )
    parser.add_argument(
        "--universe-refresh-s",
        type=float,
        default=DEFAULT_UNIVERSE_REFRESH_S,
        help="Redecouverte periodique des listings; 0 desactive le refresh.",
    )
    parser.add_argument(
        "--duration-s",
        type=float,
        default=0.0,
        help="0 = persistant; valeur >0 = session bornee utile aux smoke-tests.",
    )
    args = parser.parse_args(argv)
    try:
        return asyncio.run(
            _run(
                Path(args.root).resolve(),
                max_symbols=max(1, min(int(args.max_symbols), 100)),
                stale_after_ms=max(250, int(args.stale_after_ms)),
                duration_s=max(0.0, float(args.duration_s)),
                universe_refresh_s=max(0.0, float(args.universe_refresh_s)),
                enabled_venues=tuple(
                    venue
                    for venue in VENUES
                    if venue in {
                        token.strip().lower()
                        for token in str(args.venues).split(",")
                        if token.strip()
                    }
                ),
                symbol_shard_count=max(1, int(args.symbol_shard_count)),
                symbol_shard_index=int(args.symbol_shard_index),
                rotate_bytes=max(8, min(int(args.rotate_mb), 1536)) * 1024 * 1024,
            )
        )
    except KeyboardInterrupt:
        return 0
    except Exception as exc:
        print(f"[native-venues] arret sur exception: {type(exc).__name__}: {exc}", flush=True)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
