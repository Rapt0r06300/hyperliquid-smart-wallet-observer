"""Collecteur persistant multi-venue public/read-only.

Ce runner NE crée PAS une seconde architecture de marché. Il branche simplement
`NativeVenueCoordinator` au stockage replayable déjà existant (`TickDatasetWriter`)
et au superviseur canonique des collecteurs.

Sources natives : Bybit, OKX, Gate.io, Bitget.
Hyperliquid + Binance restent propriétaires de `tools/collecter_bbo.py`.

Sécurité : endpoints publics uniquement, aucune clé, aucune signature, aucun ordre.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import time
from collections import deque
from pathlib import Path
from typing import Any, Callable, Mapping

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE / "src"))
sys.path.insert(0, str(RACINE / "tools"))

from hl_observer.collection.native_venue_coordinator import NativeVenueCoordinator
from hl_observer.collection.native_venue_market import NativeMarketSnapshot
from hl_observer.collection.partitioned_tick_dataset import PartitionedTickDatasetWriter
from hl_observer.collection.tick_dataset import TickEnvelope
from hl_observer.datasets.v2_pipeline import build_bundle
from hl_observer.realtime.feed_quality import FeedEventKind
import heartbeat_collecteur as HB

HEARTBEAT = Path("runtime") / "data" / "native_venues_heartbeat.json"
TICK_DATASET_DIR = Path("runtime") / "data" / "market_ticks"
MARQUEUR = Path("runtime") / "data" / "lanceur_session_marqueur.txt"
QUEUE_MAX = 100_000
STREAM_NAME = "native_venues_market_ticks"
VENUES = ("bybit", "okx", "gate", "bitget")
DEFAULT_UNIVERSE_REFRESH_S = 900.0


def _atomic_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(dict(payload), ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp, path)


def snapshot_summary(snapshot: NativeMarketSnapshot) -> dict[str, Any]:
    """Résumé normalisé persistant, sans donnée d'exécution."""
    bid_size = snapshot.bids[0].size if snapshot.bids else None
    ask_size = snapshot.asks[0].size if snapshot.asks else None
    return {
        "venue": snapshot.venue,
        "coin": snapshot.coin,
        "exchange_symbol": snapshot.exchange_symbol,
        "bid": snapshot.bid,
        "ask": snapshot.ask,
        "mid": snapshot.mid,
        "spread_bps": snapshot.spread_bps,
        "bid_size": bid_size,
        "ask_size": ask_size,
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
        },
        parsed_summary=snapshot_summary(snapshot),
    )


class RecordingNativeVenueCoordinator(NativeVenueCoordinator):
    """Même coordinateur, avec un sink local après normalisation."""

    def __init__(self, *args: Any, on_snapshot: Callable[[TickEnvelope], None], **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self._on_snapshot = on_snapshot

    def _record(
        self,
        snapshot: NativeMarketSnapshot | None,
        payload: Mapping[str, object],
    ) -> NativeMarketSnapshot | None:
        if snapshot is not None:
            self._on_snapshot(envelope_from_snapshot(snapshot, payload))
        return snapshot

    def ingest_bybit(self, payload: Mapping[str, object], **kwargs: Any) -> NativeMarketSnapshot | None:
        snapshot = super().ingest_bybit(payload, **kwargs)
        # When the canonical raw tape sink is configured, the parent already
        # persisted this frame (including trade/liquidation frames that do not
        # produce a market snapshot). Avoid duplicating the same Bybit frame.
        return snapshot if self.tick_writer is not None else self._record(snapshot, payload)

    def ingest_okx(self, payload: Mapping[str, object], **kwargs: Any) -> NativeMarketSnapshot | None:
        snapshot = super().ingest_okx(payload, **kwargs)
        return snapshot if self.tick_writer is not None else self._record(snapshot, payload)

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
    rotate_bytes: int = 512 * 1024 * 1024,
) -> int:
    queue: deque[TickEnvelope] = deque()
    dropped = 0
    written = 0
    enabled_venues = tuple(venue for venue in VENUES if venue in set(enabled_venues))
    if not enabled_venues:
        raise ValueError("enabled_venues must contain at least one supported venue")
    reconnects = {venue: 0 for venue in enabled_venues}
    last_event_ms = {venue: 0 for venue in enabled_venues}
    last_exchange_ts = {venue: 0 for venue in enabled_venues}
    canonical_last_written = 0
    canonical_last_beat_ns = 0
    started = time.time()
    universe_refreshes = 0
    universe_changes = 0
    marker0 = (root / MARQUEUR).read_text(encoding="utf-8").strip() if (root / MARQUEUR).exists() else ""

    def enqueue(envelope: TickEnvelope) -> None:
        nonlocal dropped
        if len(queue) >= QUEUE_MAX:
            queue.popleft()
            dropped += 1
        venue = envelope.source_id.split("_", 1)[0].lower()
        if venue in last_event_ms:
            last_event_ms[venue] = int(envelope.received_ts_ms)
            if envelope.exchange_ts_ms is not None:
                last_exchange_ts[venue] = max(
                    int(last_exchange_ts[venue]),
                    int(envelope.exchange_ts_ms),
                )
        queue.append(envelope)

    writer = PartitionedTickDatasetWriter(
        root / TICK_DATASET_DIR,
        rotate_bytes=max(8 * 1024 * 1024, int(rotate_bytes)),
        flush_every=1,
    )

    class QueueTickWriter:
        def append(self, envelope: TickEnvelope) -> int:
            enqueue(envelope)
            return 1

    queue_tick_writer = QueueTickWriter()

    coordinator = RecordingNativeVenueCoordinator(
        on_snapshot=enqueue,
        tick_writer=queue_tick_writer,
        stale_after_ms=stale_after_ms,
        max_symbols_per_venue=max_symbols,
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
            enqueue(
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
            emitted += 1
        return emitted
    registry = await asyncio.to_thread(coordinator.discover)
    enqueue_bybit_instrument_metadata()
    await asyncio.to_thread(coordinator.refresh_clock_sync)
    counts = {venue: len(coordinator.symbols_for(venue)) for venue in enabled_venues}
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
            universe_refreshes += 1
            changed = [venue for venue in enabled_venues if before[venue] != after[venue]]
            if not changed:
                continue
            universe_changes += len(changed)
            print(
                "[native-venues] univers change: %s -> redemarrage cible"
                % ",".join(changed),
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
            if queue:
                batch = [queue.popleft() for _ in range(min(5_000, len(queue)))]
                written += writer.append_batch(batch)

            now = time.time()
            marker_path = root / MARQUEUR
            marker = marker_path.read_text(encoding="utf-8").strip() if marker_path.exists() else marker0
            stop_reason = ""
            if marker != marker0:
                stop_reason = "SESSION_MARKER_CHANGED"
            elif duration_s > 0 and now - started >= duration_s:
                stop_reason = "DURATION_REACHED"

            health = coordinator.health(now_ms=int(now * 1000))
            now_ms = int(now * 1000)
            now_mono_ns = time.monotonic_ns()
            if now_mono_ns - canonical_last_beat_ns >= 2_000_000_000:
                required = tuple(
                    venue for venue in ("bybit", "okx") if venue in enabled_venues
                )
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
            _atomic_json(
                root / HEARTBEAT,
                {
                    "schema_version": "alina.native_venues_heartbeat.v1",
                    "ts": now,
                    "duration_s": round(now - started, 3),
                    "state": "STOPPING" if stop_reason else "RUNNING",
                    "stop_reason": stop_reason or None,
                    "discovered_registry_coins": len(registry),
                    "subscribed_symbols": counts,
                    "universe_refreshes": universe_refreshes,
                    "universe_changes": universe_changes,
                    "universe_refresh_interval_s": universe_refresh_s,
                    "records_written": written,
                    "queue_depth": len(queue),
                    "queue_drops": dropped,
                    "reconnects": reconnects,
                    "last_event_ms": last_event_ms,
                    "last_exchange_ts": last_exchange_ts,
                    "required_venues": list(required),
                    "required_venues_ready": all(
                        counts.get(venue, 0) > 0 and last_event_ms.get(venue, 0) > 0
                        for venue in required
                    ),
                    "coordinator_health": health,
                    "dataset": writer.stats(),
                    "read_only": True,
                    "real_execution": False,
                },
            )
            if stop_reason:
                break
    finally:
        current_tasks = list(managed_tasks)
        for task in current_tasks:
            if not task.done():
                task.cancel()
        await asyncio.gather(*current_tasks, return_exceptions=True)
        while queue:
            batch = [queue.popleft() for _ in range(min(5_000, len(queue)))]
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
        )
        final = {
            "schema_version": "alina.native_venues_heartbeat.v1",
            "ts": time.time(),
            "duration_s": round(time.time() - started, 3),
            "state": "STOPPED",
            "discovered_registry_coins": len(registry),
            "subscribed_symbols": counts,
            "universe_refreshes": universe_refreshes,
            "universe_changes": universe_changes,
            "universe_refresh_interval_s": universe_refresh_s,
            "records_written": written,
            "queue_depth": len(queue),
            "queue_drops": dropped,
            "reconnects": reconnects,
            "last_event_ms": last_event_ms,
            "last_exchange_ts": last_exchange_ts,
            "required_venues": [
                venue for venue in ("bybit", "okx") if venue in enabled_venues
            ],
            "required_venues_ready": all(
                counts.get(venue, 0) > 0 and last_event_ms.get(venue, 0) > 0
                for venue in ("bybit", "okx") if venue in enabled_venues
            ),
            "dataset": writer.stats(),
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
