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

from hl_observer.collection.native_venue_coordinator import NativeVenueCoordinator
from hl_observer.collection.native_venue_market import NativeMarketSnapshot
from hl_observer.collection.tick_dataset import TickDatasetWriter, TickEnvelope
from hl_observer.realtime.feed_quality import FeedEventKind

HEARTBEAT = Path("runtime") / "data" / "native_venues_heartbeat.json"
TICK_DATASET_DIR = Path("runtime") / "data" / "market_ticks"
MARQUEUR = Path("runtime") / "data" / "lanceur_session_marqueur.txt"
QUEUE_MAX = 100_000
STREAM_NAME = "native_venues_market_ticks"
VENUES = ("bybit", "okx", "gate", "bitget")


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
        local_monotonic_ns=monotonic_ns if monotonic_ns is not None else time.monotonic_ns(),
        sequence=snapshot.sequence,
        provenance={
            "venue": snapshot.venue,
            "access": "public_read_only",
            "transport": "websocket",
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
        return self._record(super().ingest_bybit(payload, **kwargs), payload)

    def ingest_okx(self, payload: Mapping[str, object], **kwargs: Any) -> NativeMarketSnapshot | None:
        return self._record(super().ingest_okx(payload, **kwargs), payload)

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
) -> int:
    queue: deque[TickEnvelope] = deque()
    dropped = 0
    written = 0
    reconnects = {venue: 0 for venue in VENUES}
    last_event_ms = {venue: 0 for venue in VENUES}
    started = time.time()
    marker0 = (root / MARQUEUR).read_text(encoding="utf-8").strip() if (root / MARQUEUR).exists() else ""

    def enqueue(envelope: TickEnvelope) -> None:
        nonlocal dropped
        if len(queue) >= QUEUE_MAX:
            queue.popleft()
            dropped += 1
        venue = envelope.source_id.split("_", 1)[0].lower()
        if venue in last_event_ms:
            last_event_ms[venue] = int(envelope.received_ts_ms)
        queue.append(envelope)

    coordinator = RecordingNativeVenueCoordinator(
        on_snapshot=enqueue,
        stale_after_ms=stale_after_ms,
        max_symbols_per_venue=max_symbols,
        ccxt_snapshot_path=root / "data" / "ccxt_universe.json",
    )
    registry = await asyncio.to_thread(coordinator.discover)
    counts = {venue: len(coordinator.symbols_for(venue)) for venue in VENUES}
    if not any(counts.values()):
        print("[native-venues] aucun marche decouvert sur Bybit/OKX/Gate/Bitget", flush=True)
        return 2

    writer = TickDatasetWriter(
        root / TICK_DATASET_DIR,
        stream_name=STREAM_NAME,
        rotate_bytes=128 * 1024 * 1024,
        flush_every=1,
    )

    async def venue_loop(venue: str) -> None:
        method = getattr(coordinator, f"run_{venue}")
        while True:
            try:
                await method()
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

    tasks = [asyncio.create_task(venue_loop(venue)) for venue in VENUES]
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
                    "records_written": written,
                    "queue_depth": len(queue),
                    "queue_drops": dropped,
                    "reconnects": reconnects,
                    "last_event_ms": last_event_ms,
                    "coordinator_health": health,
                    "dataset": writer.stats(),
                    "read_only": True,
                    "real_execution": False,
                },
            )
            if stop_reason:
                break
    finally:
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        while queue:
            batch = [queue.popleft() for _ in range(min(5_000, len(queue)))]
            written += writer.append_batch(batch)
        final = {
            "schema_version": "alina.native_venues_heartbeat.v1",
            "ts": time.time(),
            "duration_s": round(time.time() - started, 3),
            "state": "STOPPED",
            "discovered_registry_coins": len(registry),
            "subscribed_symbols": counts,
            "records_written": written,
            "queue_depth": len(queue),
            "queue_drops": dropped,
            "reconnects": reconnects,
            "last_event_ms": last_event_ms,
            "dataset": writer.stats(),
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
    parser.add_argument("--stale-after-ms", type=int, default=1_500)
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
            )
        )
    except KeyboardInterrupt:
        return 0
    except Exception as exc:
        print(f"[native-venues] arret sur exception: {type(exc).__name__}: {exc}", flush=True)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
