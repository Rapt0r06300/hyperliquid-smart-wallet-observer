#!/usr/bin/env python3
"""Bounded GitHub-hosted public market collection window for Alina Dataset V2.

No credentials, account endpoints, orders or self-hosted resources are used. The
collector writes partitioned raw TickEnvelope shards, then derives V2 manifests
from the immutable gzip bytes that were actually written.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import shutil
import time
import uuid
from collections import defaultdict
from pathlib import Path
from typing import Any, Mapping

import websockets

from hl_observer.collection.binance_depth_live import BinanceDepthLiveCollector
from hl_observer.collection.binance_market_context import BinanceMarketContextCollector
from hl_observer.collection.bybit_market_data import BybitPublicClient
from hl_observer.collection.native_market_tape import native_tick_envelope
from hl_observer.collection.okx_market_data import OkxPublicClient
from hl_observer.collection.partitioned_tick_dataset import PartitionedTickDatasetWriter
from hl_observer.collection.tick_dataset import TickEnvelope
from hl_observer.datasets.v2_export import build_manifest_from_tick_shard, write_manifest
from hl_observer.datasets.v2_pipeline import (
    V2_REPOSITORY,
    V2_SCHEMA,
    finalize_manifest,
)
from hl_observer.realtime.feed_quality import FeedEventKind

WS_HYPERLIQUID = "wss://api.hyperliquid.xyz/ws"
WS_BINANCE_PUBLIC = "wss://fstream.binance.com/public/stream"
WS_BINANCE_MARKET = "wss://fstream.binance.com/market/stream"


class AsyncPartitionSink:
    """Bounded non-blocking ingress with one durable batch-writer worker."""

    def __init__(
        self,
        writer: PartitionedTickDatasetWriter,
        *,
        max_queue: int = 200_000,
        batch_size: int = 2_000,
        flush_interval_s: float = 0.25,
    ) -> None:
        self.writer = writer
        self.queue: asyncio.Queue[TickEnvelope] = asyncio.Queue(maxsize=max(1, int(max_queue)))
        self.batch_size = max(1, int(batch_size))
        self.flush_interval_s = max(0.01, float(flush_interval_s))
        self.drops: dict[tuple[str, str, str], int] = defaultdict(int)
        self.accepted = 0
        self.persisted = 0
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
            batch: list[TickEnvelope] = []
            try:
                first = await asyncio.wait_for(
                    self.queue.get(),
                    timeout=self.flush_interval_s,
                )
            except TimeoutError:
                continue
            batch.append(first)
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


def _hyperliquid_envelope(
    message: Mapping[str, Any],
    *,
    received_ts_ms: int,
    receive_mono_ns: int,
    connection_id: str,
) -> TickEnvelope | None:
    channel = str(message.get("channel") or "")
    data = message.get("data")
    instrument = ""
    exchange_ts: int | None = None
    event_kind: FeedEventKind | str
    event_count = 1

    if channel in {"bbo", "l2Book"} and isinstance(data, Mapping):
        instrument = str(data.get("coin") or "").upper()
        exchange_ts = _int(data.get("time"))
        event_kind = FeedEventKind.SNAPSHOT
    elif channel == "trades" and isinstance(data, list):
        rows = [row for row in data if isinstance(row, Mapping)]
        if not rows:
            return None
        instrument = str(rows[0].get("coin") or "").upper()
        times = [_int(row.get("time")) for row in rows]
        present = [value for value in times if value is not None]
        exchange_ts = max(present) if present else None
        event_kind = FeedEventKind.EVENT
        event_count = len(rows)
    elif channel == "activeAssetCtx" and isinstance(data, Mapping):
        instrument = str(data.get("coin") or "").upper()
        ctx = data.get("ctx")
        if not isinstance(ctx, Mapping):
            return None
        # Hyperliquid does not attach an event timestamp to activeAssetCtx.
        # Preserve that fact instead of fabricating one.
        exchange_ts = None
        event_kind = FeedEventKind.SNAPSHOT
    else:
        return None

    if not instrument:
        return None
    parsed_summary: dict[str, Any] = {
        "event_count": event_count,
        "data_gate_ready": False,
    }
    if channel == "activeAssetCtx" and isinstance(data, Mapping):
        ctx = data.get("ctx")
        if isinstance(ctx, Mapping):
            parsed_summary.update(
                {
                    "mark_price": _float(ctx.get("markPx")),
                    "mid_price": _float(ctx.get("midPx")),
                    "oracle_price": _float(ctx.get("oraclePx")),
                    "funding_rate": _float(ctx.get("funding")),
                    "open_interest": _float(ctx.get("openInterest")),
                    "premium": _float(ctx.get("premium")),
                    "day_notional_volume": _float(ctx.get("dayNtlVlm")),
                    "prev_day_price": _float(ctx.get("prevDayPx")),
                }
            )
    return TickEnvelope(
        source_id="hyperliquid_public_ws",
        channel=channel,
        instrument=instrument,
        event_kind=event_kind,
        raw_payload=dict(message),
        exchange_ts_ms=exchange_ts,
        received_ts_ms=int(received_ts_ms),
        local_monotonic_ns=int(receive_mono_ns),
        connection_id=connection_id,
        sequence=None,
        provenance={
            "url": WS_HYPERLIQUID,
            "network": "mainnet",
            "access": "read_only",
            "transport": "websocket",
            "authenticated": False,
        },
        parsed_summary=parsed_summary,
    )


def _binance_bbo_envelope(
    payload: Mapping[str, Any],
    *,
    received_ts_ms: int,
    receive_mono_ns: int,
    connection_id: str,
) -> TickEnvelope | None:
    raw = payload.get("data") if isinstance(payload.get("data"), Mapping) else payload
    if not isinstance(raw, Mapping):
        return None
    symbol = str(raw.get("s") or "").upper()
    bid = _float(raw.get("b"))
    ask = _float(raw.get("a"))
    if not symbol or bid is None or ask is None or bid <= 0 or ask < bid:
        return None
    sequence = _int(raw.get("u"))
    exchange_ts = _int(raw.get("T")) or _int(raw.get("E"))
    return TickEnvelope(
        source_id="binance_usdm_public",
        channel="bbo",
        instrument=symbol,
        event_kind=FeedEventKind.SNAPSHOT,
        raw_payload=dict(raw),
        exchange_ts_ms=exchange_ts,
        received_ts_ms=received_ts_ms,
        local_monotonic_ns=receive_mono_ns,
        connection_id=connection_id,
        sequence=sequence,
        provenance={
            "url": WS_BINANCE_PUBLIC,
            "network": "mainnet",
            "access": "read_only",
            "transport": "websocket",
            "authenticated": False,
        },
        parsed_summary={
            "best_bid": bid,
            "best_ask": ask,
            "bid_size": _float(raw.get("B")),
            "ask_size": _float(raw.get("A")),
            "data_gate_ready": False,
        },
    )


def _binance_trade_envelope(
    payload: Mapping[str, Any],
    *,
    received_ts_ms: int,
    receive_mono_ns: int,
    connection_id: str,
) -> TickEnvelope | None:
    raw = payload.get("data") if isinstance(payload.get("data"), Mapping) else payload
    if not isinstance(raw, Mapping) or str(raw.get("e") or "") not in {"trade", "aggTrade"}:
        return None
    symbol = str(raw.get("s") or "").upper()
    price = _float(raw.get("p"))
    size = _float(raw.get("q"))
    if not symbol or price is None or size is None or price <= 0 or size <= 0:
        return None
    sequence = _int(raw.get("t")) or _int(raw.get("a"))
    return TickEnvelope(
        source_id="binance_usdm_public",
        channel="trades",
        instrument=symbol,
        event_kind=FeedEventKind.EVENT,
        raw_payload=dict(raw),
        exchange_ts_ms=_int(raw.get("T")) or _int(raw.get("E")),
        received_ts_ms=received_ts_ms,
        local_monotonic_ns=receive_mono_ns,
        connection_id=connection_id,
        sequence=sequence,
        provenance={
            "url": WS_BINANCE_MARKET,
            "network": "mainnet",
            "access": "read_only",
            "transport": "websocket",
            "authenticated": False,
        },
        parsed_summary={
            "price": price,
            "size": size,
            "aggressor_side": "SELL" if raw.get("m") is True else "BUY",
            "data_gate_ready": False,
        },
    )


async def _native_with_clock_sync(
    venue: str,
    client: Any,
    symbols: list[str],
    sink: AsyncPartitionSink,
    *,
    probe_interval_s: float = 60.0,
) -> None:
    sync: dict[str, float | int] = {}

    async def refresh_probe() -> None:
        try:
            sample = await asyncio.to_thread(client.measure_clock_sync)
            sync["offset_ms"] = float(sample.offset_ms)
            sync["rtt_ms"] = float(sample.rtt_ms)
            sync["server_ts_ms"] = int(sample.server_ts_ms)
            sync["probe_receive_wall_ts_ms"] = int(sample.receive_wall_ts_ms)
        except asyncio.CancelledError:
            raise
        except Exception:
            # Missing clock evidence must remain missing; raw market capture continues.
            sync.clear()

    async def probe_loop() -> None:
        while True:
            await asyncio.sleep(max(10.0, float(probe_interval_s)))
            await refresh_probe()

    # Acquire one explicit sample before admitting market frames when possible.
    await refresh_probe()
    probe_task = asyncio.create_task(probe_loop())
    try:
        async for payload in client.messages(symbols):
            message = dict(payload)
            meta = message.get("_alina_transport")
            transport = dict(meta) if isinstance(meta, Mapping) else {}
            if sync:
                transport["clock_offset_ms"] = sync.get("offset_ms")
                transport["clock_probe_rtt_ms"] = sync.get("rtt_ms")
                transport["clock_probe_server_ts_ms"] = sync.get("server_ts_ms")
                transport["clock_probe_receive_wall_ts_ms"] = sync.get(
                    "probe_receive_wall_ts_ms"
                )
            message["_alina_transport"] = transport
            envelope = native_tick_envelope(venue, message)
            if envelope is not None:
                sink.emit(envelope)
    finally:
        probe_task.cancel()
        await asyncio.gather(probe_task, return_exceptions=True)


async def _native_bybit(symbols: list[str], sink: AsyncPartitionSink) -> None:
    await _native_with_clock_sync(
        "bybit",
        BybitPublicClient(orderbook_depth=200),
        symbols,
        sink,
    )


async def _native_okx(symbols: list[str], sink: AsyncPartitionSink) -> None:
    await _native_with_clock_sync(
        "okx",
        OkxPublicClient(),
        symbols,
        sink,
    )


async def _hyperliquid(coins: list[str], sink: AsyncPartitionSink) -> None:
    reconnects = 0
    while True:
        connection_id = f"hl-cloud-{uuid.uuid4().hex}"
        try:
            async with websockets.connect(
                WS_HYPERLIQUID,
                ping_interval=20,
                ping_timeout=10,
                close_timeout=5,
                max_size=2**23,
            ) as socket:
                for coin in coins:
                    for channel in ("bbo", "l2Book", "trades", "activeAssetCtx"):
                        await socket.send(
                            json.dumps(
                                {
                                    "method": "subscribe",
                                    "subscription": {"type": channel, "coin": coin},
                                }
                            )
                        )
                async for raw_text in socket:
                    receive_mono_ns = time.monotonic_ns()
                    receive_wall_ms = int(time.time() * 1_000)
                    try:
                        message = json.loads(raw_text)
                    except (TypeError, ValueError):
                        continue
                    if not isinstance(message, Mapping):
                        continue
                    envelope = _hyperliquid_envelope(
                        message,
                        received_ts_ms=receive_wall_ms,
                        receive_mono_ns=receive_mono_ns,
                        connection_id=connection_id,
                    )
                    if envelope is not None:
                        envelope.reconnect_count = reconnects
                        sink.emit(envelope)
        except asyncio.CancelledError:
            raise
        except Exception:
            reconnects += 1
            await asyncio.sleep(min(30.0, 2.0 ** min(reconnects, 5)))


async def _binance_stream(
    symbols: list[str],
    sink: AsyncPartitionSink,
    *,
    mode: str,
) -> None:
    if mode == "bbo":
        base = WS_BINANCE_PUBLIC
        suffix = "bookTicker"
        parser = _binance_bbo_envelope
    elif mode == "trades":
        base = WS_BINANCE_MARKET
        suffix = "trade"
        parser = _binance_trade_envelope
    else:
        raise ValueError(mode)

    streams = "/".join(f"{symbol.lower()}@{suffix}" for symbol in symbols)
    reconnects = 0
    while True:
        connection_id = f"bin-{mode}-{uuid.uuid4().hex}"
        try:
            async with websockets.connect(
                f"{base}?streams={streams}",
                ping_interval=20,
                ping_timeout=10,
                close_timeout=5,
                max_size=2**23,
            ) as socket:
                async for raw_text in socket:
                    mono = time.monotonic_ns()
                    wall = int(time.time() * 1_000)
                    try:
                        payload = json.loads(raw_text)
                    except (TypeError, ValueError):
                        continue
                    if not isinstance(payload, Mapping):
                        continue
                    envelope = parser(
                        payload,
                        received_ts_ms=wall,
                        receive_mono_ns=mono,
                        connection_id=connection_id,
                    )
                    if envelope is not None:
                        envelope.reconnect_count = reconnects
                        sink.emit(envelope)
        except asyncio.CancelledError:
            raise
        except Exception:
            reconnects += 1
            await asyncio.sleep(min(30.0, 2.0 ** min(reconnects, 5)))


def _bundle_index(
    manifests: list[dict[str, Any]],
    *,
    collector_version: str,
    queue_drops: Mapping[tuple[str, str, str], int],
) -> dict[str, Any]:
    return {
        "schema": V2_SCHEMA,
        "repository": V2_REPOSITORY,
        "collector_version": str(collector_version),
        "collection_queue_drops": sum(
            max(0, int(value)) for value in queue_drops.values()
        ),
        "shard_count": len(manifests),
        "safe_count": sum(
            1 for row in manifests if row.get("quality_status") == "SAFE"
        ),
        "partial_count": sum(
            1 for row in manifests if row.get("quality_status") == "PARTIAL"
        ),
        "reject_count": sum(
            1 for row in manifests if row.get("quality_status") == "REJECT"
        ),
        "dataset_ids": [str(row["dataset_id"]) for row in manifests],
        "manifests": [
            f"manifests/{row['dataset_id']}.json"
            for row in manifests
        ],
        "assets": [
            f"assets/{row['release_asset']}"
            for row in manifests
        ],
        "read_only": True,
        "real_execution": False,
    }


def _load_plan_rows(path: Path) -> list[dict[str, Any]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, Mapping):
        raise ValueError("collection plan must be a JSON object")
    raw_rows = payload.get("coins")
    if not isinstance(raw_rows, list):
        raw_rows = payload.get("selected")
    if not isinstance(raw_rows, list):
        raise ValueError("collection plan must contain coins or selected")
    rows: list[dict[str, Any]] = []
    for raw in raw_rows:
        if not isinstance(raw, Mapping):
            continue
        coin = str(raw.get("coin") or "").strip().upper()
        symbols = raw.get("symbols")
        if not coin or not isinstance(symbols, Mapping):
            continue
        normalized = {
            str(venue).strip().lower(): str(symbol).strip().upper()
            for venue, symbol in symbols.items()
            if str(venue).strip() and str(symbol).strip()
        }
        if normalized:
            rows.append({"coin": coin, "symbols": normalized})
    if not rows:
        raise ValueError("collection plan contains no usable markets")
    return rows


def _venue_lists(
    coins: list[str],
    plan_rows: list[dict[str, Any]] | None,
) -> dict[str, list[str]]:
    if plan_rows is None:
        return {
            "hyperliquid": list(coins),
            "binance": [f"{coin}USDT" for coin in coins],
            "bybit": [f"{coin}USDT" for coin in coins],
            "okx": [f"{coin}-USDT-SWAP" for coin in coins],
        }
    result = {"hyperliquid": [], "binance": [], "bybit": [], "okx": []}
    for row in plan_rows:
        symbols = row["symbols"]
        for venue in result:
            symbol = symbols.get(venue)
            if symbol:
                result[venue].append(str(symbol))
    for venue in result:
        result[venue] = sorted(set(result[venue]))
    return result


async def collect(
    output: Path,
    *,
    coins: list[str],
    duration_s: float,
    collector_version: str,
    rotate_bytes: int,
    plan_rows: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    raw_root = output / "raw"
    assets_root = output / "assets"
    manifests_root = output / "manifests"
    assets_root.mkdir(parents=True, exist_ok=True)
    manifests_root.mkdir(parents=True, exist_ok=True)

    writer = PartitionedTickDatasetWriter(
        raw_root,
        rotate_bytes=rotate_bytes,
        flush_every=1,
    )
    sink = AsyncPartitionSink(writer)
    writer_task = asyncio.create_task(sink.run())

    venue_lists = _venue_lists(coins, plan_rows)
    hl_coins = venue_lists["hyperliquid"]
    bybit_symbols = venue_lists["bybit"]
    okx_symbols = venue_lists["okx"]
    binance_symbols = venue_lists["binance"]

    binance_depth = BinanceDepthLiveCollector(
        binance_symbols,
        tick_sink=sink.emit,
        publication_depth=200,
        snapshot_limit=1000,
    )
    binance_context = BinanceMarketContextCollector(
        binance_symbols,
        tick_sink=sink.emit,
    )

    tasks: list[asyncio.Task[Any]] = []
    if bybit_symbols:
        tasks.append(asyncio.create_task(_native_bybit(bybit_symbols, sink)))
    if okx_symbols:
        tasks.append(asyncio.create_task(_native_okx(okx_symbols, sink)))
    if hl_coins:
        tasks.append(asyncio.create_task(_hyperliquid(hl_coins, sink)))
    if binance_symbols:
        tasks.extend(
            (
                asyncio.create_task(_binance_stream(binance_symbols, sink, mode="bbo")),
                asyncio.create_task(_binance_stream(binance_symbols, sink, mode="trades")),
                asyncio.create_task(binance_depth.run()),
                asyncio.create_task(binance_context.run()),
            )
        )
    if not tasks:
        raise RuntimeError("collection plan contains no supported venue streams")
    started = int(time.time() * 1_000)
    try:
        await asyncio.sleep(max(1.0, float(duration_s)))
    finally:
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        await sink.close()
        await writer_task

    shards = await asyncio.to_thread(writer.rotate_all)
    manifests: list[dict[str, Any]] = []
    for shard in shards:
        manifest = await asyncio.to_thread(
            build_manifest_from_tick_shard,
            shard,
            collector_version=collector_version,
            reconciliation_status="UNVERIFIED",
        )
        key = (
            str(manifest["source"]),
            str(manifest["family"]),
            str(manifest["symbol"]),
        )
        drops = int(sink.drops.get(key, 0))
        if drops:
            manifest["integrity"]["gap_count"] = (
                int(manifest["integrity"].get("gap_count") or 0) + drops
            )
            manifest["collection_queue_drops"] = drops
        manifest = finalize_manifest(manifest)

        asset_name = f"{manifest['dataset_id']}.jsonl.gz"
        asset_path = assets_root / asset_name
        shutil.move(str(shard), asset_path)
        manifest["release_asset"] = asset_name
        manifest["bytes"] = asset_path.stat().st_size
        manifest_path = manifests_root / f"{manifest['dataset_id']}.json"
        write_manifest(manifest, manifest_path)
        manifests.append(manifest)

    bundle_index = _bundle_index(
        manifests,
        collector_version=collector_version,
        queue_drops=sink.drops,
    )
    write_manifest(bundle_index, output / "BUNDLE_INDEX.json")

    summary = {
        "schema": "alina.cloud_collection_window.v1",
        "started_at_ms": started,
        "ended_at_ms": int(time.time() * 1_000),
        "duration_s": round((int(time.time() * 1_000) - started) / 1000.0, 3),
        "coins": coins,
        "venue_symbols": venue_lists,
        "collector_version": collector_version,
        "accepted_frames": sink.accepted,
        "persisted_frames": sink.persisted,
        "queue_drops": {
            "|".join(key): value for key, value in sorted(sink.drops.items())
        },
        "asset_count": len(manifests),
        "bundle_index": {
            "schema": bundle_index["schema"],
            "shard_count": bundle_index["shard_count"],
            "safe_count": bundle_index["safe_count"],
            "partial_count": bundle_index["partial_count"],
            "reject_count": bundle_index["reject_count"],
        },
        "assets": [
            {
                "dataset_id": row["dataset_id"],
                "release_asset": row["release_asset"],
                "source": row["source"],
                "family": row["family"],
                "symbol": row["symbol"],
                "event_count": row["event_count"],
                "quality_status": row["quality_status"],
            }
            for row in manifests
        ],
        "binance_depth": binance_depth.health(),
        "binance_context": binance_context.health(),
        "read_only": True,
        "real_execution": False,
    }
    (output / "collection_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return summary


def _int(value: Any) -> int | None:
    try:
        return int(float(value)) if value is not None else None
    except (TypeError, ValueError, OverflowError):
        return None


def _float(value: Any) -> float | None:
    try:
        return float(value) if value is not None else None
    except (TypeError, ValueError, OverflowError):
        return None


def main() -> int:
    parser = argparse.ArgumentParser(description="Collect one bounded public market-data window.")
    parser.add_argument("--output", required=True)
    parser.add_argument("--coins", default="BTC,ETH,SOL")
    parser.add_argument("--plan-file")
    parser.add_argument("--duration-s", type=float, default=120.0)
    parser.add_argument("--collector-version", required=True)
    parser.add_argument("--rotate-mb", type=int, default=64)
    args = parser.parse_args()

    plan_rows = _load_plan_rows(Path(args.plan_file)) if args.plan_file else None
    if plan_rows is not None:
        coins = sorted({str(row["coin"]).upper() for row in plan_rows})
    else:
        coins = sorted(
            {
                token.strip().upper()
                for token in str(args.coins).split(",")
                if token.strip()
            }
        )
    if not coins:
        raise SystemExit("no coins")
    summary = asyncio.run(
        collect(
            Path(args.output),
            coins=coins,
            duration_s=max(1.0, float(args.duration_s)),
            collector_version=args.collector_version,
            rotate_bytes=max(1, int(args.rotate_mb)) * 1024 * 1024,
            plan_rows=plan_rows,
        )
    )
    print(json.dumps(summary, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
