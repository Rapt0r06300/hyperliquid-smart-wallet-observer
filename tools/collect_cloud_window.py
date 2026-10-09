#!/usr/bin/env python3
"""Bounded GitHub-hosted public market collection window for Alina Dataset V2.

No credentials, account endpoints, orders or self-hosted resources are used. The
collector writes partitioned raw TickEnvelope shards, then derives V2 manifests
from the immutable gzip bytes that were actually written.
"""
from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import shutil
import time
import uuid
from collections import defaultdict
from pathlib import Path
from typing import Any, Mapping

import httpx
import websockets

from hl_observer.collection.binance_clock_sync import BinanceClockSyncProbe
from hl_observer.collection.binance_depth_live import BinanceDepthLiveCollector
from hl_observer.collection.binance_funding_history import (
    fetch_binance_funding_settlements,
)
from hl_observer.collection.binance_market_context import BinanceMarketContextCollector
from hl_observer.collection.hyperliquid_clock_sync import HyperliquidClockSyncProbe
from hl_observer.collection.hyperliquid_funding_history import (
    fetch_hyperliquid_funding_settlements,
)
from hl_observer.collection.native_funding_history import (
    fetch_bitget_funding_settlements,
    fetch_bybit_funding_settlements,
    fetch_gate_funding_settlements,
    fetch_okx_funding_settlements,
)
from hl_observer.collection.bybit_market_data import BybitMarketState, BybitPublicClient
from hl_observer.collection.bitget_market_data import BitgetMarketState, BitgetPublicClient
from hl_observer.collection.depth_capacity import (
    capacity_tape_envelope,
    cross_venue_capacity_envelope,
)
from hl_observer.collection.gate_market_data import GateMarketState, GatePublicClient
from hl_observer.collection.native_market_tape import (
    native_instrument_metadata_envelope,
    native_tick_envelopes,
)
from hl_observer.collection.native_venue_market import canonical_coin
from hl_observer.collection.okx_market_data import OkxMarketState, OkxPublicClient
from hl_observer.collection.partitioned_tick_dataset import PartitionedTickDatasetWriter
from hl_observer.collection.tick_dataset import TickEnvelope
from hl_observer.collection.trade_reconciliation import (
    HyperliquidTradeReferenceSampler,
    reconcile_binance_aggtrade_shard,
    reconcile_bitget_trade_shard,
    reconcile_bybit_trade_shard,
    reconcile_gate_trade_shard,
    reconcile_okx_trade_shard,
)
from hl_observer.datasets.v2_export import build_manifest_from_tick_shard, write_manifest
from hl_observer.datasets.v2_pipeline import (
    V2_REPOSITORY,
    V2_SCHEMA,
    attach_reconciliation,
    finalize_manifest,
)
from hl_observer.realtime.feed_quality import FeedEventKind

WS_HYPERLIQUID = "wss://api.hyperliquid.xyz/ws"
INFO_HYPERLIQUID = "https://api.hyperliquid.xyz/info"
WS_BINANCE_PUBLIC = "wss://fstream.binance.com/public/stream"
WS_BINANCE_MARKET = "wss://fstream.binance.com/market/stream"
L2_REQUIRED_VENUES = frozenset({"hyperliquid", "binance", "bybit", "okx", "gate", "bitget"})


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
        # Keep bounded temporal attribution for each dropped frame. A single
        # cumulative drop counter must NOT poison every rotated shard of the
        # same symbol (and cannot reconstruct frames that were actually lost).
        self.drop_windows: dict[tuple[str, str, str, str, int], int] = defaultdict(int)
        self.accepted = 0
        self.persisted = 0
        self.backpressure_events = 0
        self._stop = False
        self._latest_capacity: dict[tuple[str, str], TickEnvelope] = {}

    @staticmethod
    def key(envelope: TickEnvelope) -> tuple[str, str, str]:
        return (
            str(envelope.source_id),
            str(envelope.channel),
            str(envelope.instrument),
        )

    def _capacity_pairs(self, envelope: TickEnvelope) -> list[TickEnvelope]:
        if envelope.channel != "capacity_tape":
            return []
        coin = str(envelope.parsed_summary.get("coin") or "").upper()
        venue = str(envelope.parsed_summary.get("venue") or "").lower()
        if not coin or not venue:
            return []
        peers = [
            row for (peer_coin, peer_venue), row in self._latest_capacity.items()
            if peer_coin == coin and peer_venue != venue
        ]
        self._latest_capacity[(coin, venue)] = envelope
        return [
            paired
            for peer in peers
            if (paired := cross_venue_capacity_envelope(peer, envelope)) is not None
        ]

    def emit(self, envelope: TickEnvelope) -> None:
        """Legacy synchronous callback; any queue overflow remains explicit."""
        if not self._put(envelope):
            return
        for paired in self._capacity_pairs(envelope):
            self._put(paired)

    async def emit_async(self, envelope: TickEnvelope) -> None:
        """Backpressure async market producers instead of dropping raw frames."""
        if self.queue.full():
            self.backpressure_events += 1
        await self.queue.put(envelope)
        self.accepted += 1
        for paired in self._capacity_pairs(envelope):
            if self.queue.full():
                self.backpressure_events += 1
            await self.queue.put(paired)
            self.accepted += 1

    def _put(self, envelope: TickEnvelope) -> bool:
        try:
            self.queue.put_nowait(envelope)
            self.accepted += 1
            return True
        except asyncio.QueueFull:
            self.drops[self.key(envelope)] += 1
            try:
                received_second = int(getattr(envelope, "received_ts_ms", None))
            except (TypeError, ValueError, OverflowError):
                received_second = -1
            self.drop_windows[
                (*self.key(envelope), str(getattr(envelope, "connection_id", None) or ""), received_second)
            ] += 1
            return False

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


def orphaned_queue_drops(
    manifests: list[Mapping[str, Any]],
    dropped: Mapping[tuple[str, str, str], int],
) -> dict[str, int]:
    """Missing partitions stay visible even when no shard could be persisted."""
    available = {
        (str(row.get("source") or ""), str(row.get("family") or ""),
         str(row.get("symbol") or ""))
        for row in manifests
    }
    return {
        "|".join(key): int(count)
        for key, count in sorted(dropped.items())
        if key not in available and int(count) > 0
    }


def attribute_queue_drops(
    manifests: list[Mapping[str, Any]],
    dropped: Mapping[tuple[str, str, str], int],
    drop_windows: Mapping[tuple[str, str, str, str, int], int],
    *,
    timestamps_are_ms: bool = False,
) -> list[int]:
    """Attribute *real* ingress losses to the impacted immutable shards.

    Time and causal connection identity are taken only from capture evidence.
    Unknown times/connections are conservatively attached to all possible
    shards; never make unrelated prior shards REJECT because a later drop occurred.
    """
    positions: dict[tuple[str, str, str], list[int]] = defaultdict(list)
    for index, manifest in enumerate(manifests):
        positions[(
            str(manifest.get("source") or ""),
            str(manifest.get("family") or ""),
            str(manifest.get("symbol") or ""),
        )].append(index)
    attribution = [0] * len(manifests)
    counts_by_key: dict[tuple[str, str, str], int] = defaultdict(int)
    for (*key_values, connection, second), count in sorted(drop_windows.items()):
        key = tuple(key_values)
        if len(key) != 3 or int(count) <= 0:
            raise ValueError("invalid queue-drop evidence")
        counts_by_key[key] += int(count)
        candidates = positions.get(key, [])
        if not candidates:
            # Preserve other venues; orphaned losses are reported in bundle receipts.
            continue
        if connection:
            matches = [
                index for index in candidates
                if connection in (
                    (manifests[index].get("synchronization") or {}).get("connection_ids") or []
                )
            ]
            if matches:
                candidates = matches
        if second < 0:
            # Timestamp untrustworthy: all possible shards remain uncertain.
            for index in candidates:
                attribution[index] += int(count)
            continue
        # New collection records exact receive milliseconds. Legacy callers
        # continue using second-resolution evidence until migrated.
        lower, upper = (
            (int(second), int(second))
            if timestamps_are_ms
            else (int(second) * 1000, (int(second) + 1) * 1000 - 1)
        )
        distance_by_index: dict[int, int] = {}
        for index in candidates:
            first = int(manifests[index].get("start_ts_ms") or 0)
            last = int(manifests[index].get("end_ts_ms") or first)
            distance_by_index[index] = (
                first - upper if upper < first
                else lower - last if lower > last
                else 0
            )
        closest = min(distance_by_index.values())
        for index, distance in distance_by_index.items():
            if distance == closest:
                attribution[index] += int(count)
    for key, total in dropped.items():
        explained = counts_by_key.get(key, 0)
        if total < explained:
            raise ValueError(f"queue-drop evidence exceeds observed ingress losses: {key}")
        if total == explained:
            continue
        candidates = positions.get(key, [])
        if not candidates:
            continue
        # Legacy callers lacking precise timestamps remain fail-closed.
        for index in candidates:
            attribution[index] += total - explained
    return attribution


async def _emit_with_backpressure(sink: Any, envelope: TickEnvelope) -> None:
    async_emit = getattr(sink, "emit_async", None)
    if callable(async_emit):
        await async_emit(envelope)
    else:
        sink.emit(envelope)


def _hyperliquid_envelope(
    message: Mapping[str, Any],
    *,
    received_ts_ms: int,
    receive_mono_ns: int,
    connection_id: str,
    clock_evidence: Mapping[str, Any] | None = None,
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
        **dict(clock_evidence or {}),
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
    provenance = {
        "url": WS_HYPERLIQUID,
        "network": "mainnet",
        "access": "read_only",
        "transport": "websocket",
        "authenticated": False,
    }
    if channel == "activeAssetCtx":
        provenance["timestamp_semantics"] = "receive_observation_time_only"
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
        provenance=provenance,
        parsed_summary=parsed_summary,
    )




def _hyperliquid_envelopes(
    message: Mapping[str, Any],
    *,
    received_ts_ms: int,
    receive_mono_ns: int,
    connection_id: str,
    clock_evidence: Mapping[str, Any] | None = None,
) -> list[TickEnvelope]:
    """Split Hyperliquid public trades without losing original batch provenance.

    Keep a malformed or unsplittable batch intact for fail-closed certification:
    silently dropping individual rows would fabricate a complete trade history.
    """
    kwargs = {
        "received_ts_ms": received_ts_ms,
        "receive_mono_ns": receive_mono_ns,
        "connection_id": connection_id,
        "clock_evidence": clock_evidence,
    }
    def original() -> list[TickEnvelope]:
        envelope = _hyperliquid_envelope(message, **kwargs)
        return [envelope] if envelope is not None else []

    if message.get("channel") != "trades":
        return original()
    rows = message.get("data")
    if not isinstance(rows, list) or len(rows) <= 1:
        return original()
    batch_digest = hashlib.sha256(json.dumps(
        dict(message), ensure_ascii=False, sort_keys=True,
        separators=(",", ":"), default=str,
    ).encode("utf-8")).hexdigest()
    split: list[TickEnvelope] = []
    for index, row in enumerate(rows):
        if not isinstance(row, Mapping) or not row.get("coin"):
            return original()
        single = dict(message)
        single["data"] = [dict(row)]
        envelope = _hyperliquid_envelope(single, **kwargs)
        if envelope is None:
            return original()
        envelope.parsed_summary.update({
            "source_batch_sha256": batch_digest,
            "source_batch_size": len(rows),
            "source_batch_index": index,
        })
        split.append(envelope)
    return split


def _binance_bbo_envelope(
    payload: Mapping[str, Any],
    *,
    received_ts_ms: int,
    receive_mono_ns: int,
    connection_id: str,
    clock_evidence: Mapping[str, Any] | None = None,
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
            **dict(clock_evidence or {}),
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
    clock_evidence: Mapping[str, Any] | None = None,
) -> TickEnvelope | None:
    raw = payload.get("data") if isinstance(payload.get("data"), Mapping) else payload
    if not isinstance(raw, Mapping) or str(raw.get("e") or "") not in {"trade", "aggTrade"}:
        return None
    symbol = str(raw.get("s") or "").upper()
    price = _float(raw.get("p"))
    size = _float(raw.get("q"))
    if not symbol or price is None or size is None or price <= 0 or size <= 0:
        return None
    event_type = str(raw.get("e") or "")
    channel = "agg_trades" if event_type == "aggTrade" else "trades"
    sequence = (
        _int(raw.get("a"))
        if event_type == "aggTrade"
        else _int(raw.get("t"))
    )
    return TickEnvelope(
        source_id="binance_usdm_public",
        channel=channel,
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
            **dict(clock_evidence or {}),
            "price": price,
            "size": size,
            "aggressor_side": "SELL" if raw.get("m") is True else "BUY",
            "aggregate_trade_id": _int(raw.get("a")),
            "first_trade_id": _int(raw.get("f")),
            "last_trade_id": _int(raw.get("l")),
            "data_gate_ready": False,
        },
    )


def _binance_liquidation_envelope(
    payload: Mapping[str, Any],
    *,
    received_ts_ms: int,
    receive_mono_ns: int,
    connection_id: str,
    clock_evidence: Mapping[str, Any] | None = None,
) -> TickEnvelope | None:
    raw = payload.get("data") if isinstance(payload.get("data"), Mapping) else payload
    if not isinstance(raw, Mapping) or str(raw.get("e") or "") != "forceOrder":
        return None
    order = raw.get("o")
    if not isinstance(order, Mapping):
        return None
    symbol = str(order.get("s") or "").upper()
    if not symbol:
        return None
    return TickEnvelope(
        source_id="binance_usdm_public",
        channel="liquidations",
        instrument=symbol,
        event_kind=FeedEventKind.EVENT,
        raw_payload=dict(raw),
        exchange_ts_ms=_int(order.get("T")) or _int(raw.get("E")),
        received_ts_ms=int(received_ts_ms),
        local_monotonic_ns=int(receive_mono_ns),
        connection_id=connection_id,
        sequence=None,
        provenance={
            "url": WS_BINANCE_MARKET,
            "network": "mainnet",
            "access": "read_only",
            "transport": "websocket",
            "authenticated": False,
            "real_execution": False,
        },
        parsed_summary={
            **dict(clock_evidence or {}),
            "side": str(order.get("S") or ""),
            "price": _float(order.get("ap") or order.get("p")),
            "size": _float(order.get("z") or order.get("q")),
            "data_gate_ready": False,
        },
    )



def _capacity_from_native_state(
    venue: str,
    state: Any,
    *,
    received_ts_ms: int,
    timing_evidence: Mapping[str, Any] | None = None,
    size_multiplier_to_base: float | None = 1.0,
    source_raw_l2_payload: Any | None = None,
) -> TickEnvelope | None:
    snapshot = state.snapshot(now_ms=int(received_ts_ms))
    return capacity_tape_envelope(
        venue=venue,
        instrument=snapshot.exchange_symbol,
        bids=snapshot.bids,
        asks=snapshot.asks,
        exchange_ts_ms=snapshot.exchange_ts_ms,
        received_ts_ms=snapshot.receive_ts_ms,
        receive_mono_ns=snapshot.receive_mono_ns,
        connection_id=snapshot.connection_id,
        sequence=snapshot.sequence,
        snapshot_id=snapshot.update_id,
        gap_count=snapshot.gap_count,
        quality=str(getattr(state, "quality", snapshot.quality)),
        timing_evidence=timing_evidence,
        size_multiplier_to_base=size_multiplier_to_base,
        source_raw_l2_payload=source_raw_l2_payload,
    )


def _native_capacity_envelope(
    venue: str,
    message: Mapping[str, Any],
    states: dict[str, Any],
    capacity_size_multipliers: Mapping[str, float],
) -> TickEnvelope | None:
    transport_raw = message.get("_alina_transport")
    transport = dict(transport_raw) if isinstance(transport_raw, Mapping) else {}
    received = _int(transport.get("receive_wall_ts_ms"))
    if received is None:
        return None
    venue_key = str(venue).lower()

    if venue_key == "bybit":
        topic = str(message.get("topic") or "")
        parts = topic.split(".")
        if not topic.startswith("orderbook.") or len(parts) < 3 or parts[1] == "1":
            return None
        data = message.get("data")
        if not isinstance(data, Mapping):
            return None
        symbol = str(data.get("s") or "").upper()
        if not symbol:
            return None
        state = states.setdefault(symbol, BybitMarketState(symbol=symbol))
        state.apply_orderbook(dict(message), receive_ts_ms=received)

    elif venue_key == "okx":
        arg = message.get("arg")
        channel = str(arg.get("channel") or "") if isinstance(arg, Mapping) else ""
        if channel != "books":
            return None
        symbol = str(arg.get("instId") or "").upper() if isinstance(arg, Mapping) else ""
        if not symbol:
            return None
        state = states.setdefault(symbol, OkxMarketState(inst_id=symbol))
        state.apply(dict(message), receive_ts_ms=received)

    elif venue_key == "gate":
        if str(message.get("channel") or "") != "futures.order_book_update":
            return None
        result = message.get("result")
        if not isinstance(result, Mapping):
            return None
        symbol = str(result.get("contract") or result.get("s") or "").upper()
        if not symbol:
            return None
        state = states.get(symbol)
        if state is None:
            # Incremental Gate depth is inadmissible without the official REST base.
            return None
        incoming_connection = str(transport.get("connection_id") or "") or None
        if (
            incoming_connection
            and state.connection_id
            and incoming_connection != state.connection_id
        ):
            # A real reconnect needs a new official base snapshot. Raw frames keep
            # flowing, but derived capacity fails closed for the remainder of this
            # bounded window instead of walking an uncertain partial book.
            states.pop(symbol, None)
            return None
        raw = dict(result)
        raw["_alina_transport"] = transport
        state.apply_book(raw, receive_ts_ms=received)

    elif venue_key == "bitget":
        arg = message.get("arg")
        channel = str(arg.get("channel") or "") if isinstance(arg, Mapping) else ""
        if channel != "books":
            return None
        symbol = str(arg.get("instId") or "").upper() if isinstance(arg, Mapping) else ""
        if not symbol:
            return None
        action = str(message.get("action") or "").lower()
        incoming_connection = str(transport.get("connection_id") or "") or None
        state = states.get(symbol)
        if state is None:
            if action != "snapshot":
                return None
            state = BitgetMarketState(symbol=symbol)
            states[symbol] = state
        elif (
            incoming_connection
            and state.connection_id
            and incoming_connection != state.connection_id
        ):
            if action != "snapshot":
                states.pop(symbol, None)
                return None
            state = BitgetMarketState(symbol=symbol)
            states[symbol] = state
        state.apply(dict(message), receive_ts_ms=received)
    else:
        return None

    return _capacity_from_native_state(
        venue_key,
        state,
        received_ts_ms=received,
        timing_evidence=transport,
        size_multiplier_to_base=capacity_size_multipliers.get(symbol),
        source_raw_l2_payload={
            key: value for key, value in message.items() if key != "_alina_transport"
        },
    )


async def _native_with_clock_sync(
    venue: str,
    client: Any,
    symbols: list[str],
    sink: AsyncPartitionSink,
    *,
    probe_interval_s: float = 60.0,
    capacity_size_multipliers: Mapping[str, float] | None = None,
) -> None:
    sync: dict[str, float | int] = {}
    capacity_states: dict[str, Any] = {}
    gate_connection_id: str | None = None
    gate_refresh_tasks: dict[str, asyncio.Task[None]] = {}
    gate_last_refresh_at: dict[str, float] = {}
    gate_refresh_slots = asyncio.Semaphore(1)
    capacity_multipliers = {
        str(symbol).upper(): float(value)
        for symbol, value in dict(capacity_size_multipliers or {}).items()
        if _float(value) is not None and float(value) > 0
    }

    async def refresh_probe() -> None:
        try:
            sample = await asyncio.to_thread(client.measure_clock_sync)
            sync["offset_ms"] = float(sample.offset_ms)
            sync["rtt_ms"] = float(sample.rtt_ms)
            uncertainty = float(getattr(sample, "uncertainty_ms", float(sample.rtt_ms) / 2.0))
            sync["uncertainty_ms"] = uncertainty
            sync["server_ts_ms"] = int(sample.server_ts_ms)
            sync["probe_receive_wall_ts_ms"] = int(sample.receive_wall_ts_ms)
            # Persist a dedicated clock receipt for real ClockSyncSample objects.
            # Lightweight test/dummy probes still enrich market frames without
            # fabricating a standalone receipt they cannot fully describe.
            if hasattr(sample, "uncertainty_ms"):
                await _emit_with_backpressure(sink, 
                    TickEnvelope(
                        source_id=f"{venue}_public_rest",
                        channel="clock_sync",
                        instrument="__VENUE__",
                        event_kind=FeedEventKind.SNAPSHOT,
                        raw_payload=sample.as_dict() if hasattr(sample, "as_dict") else {
                            "venue": venue,
                            "server_ts_ms": int(sample.server_ts_ms),
                            "receive_wall_ts_ms": int(sample.receive_wall_ts_ms),
                            "offset_ms": float(sample.offset_ms),
                            "rtt_ms": float(sample.rtt_ms),
                            "uncertainty_ms": uncertainty,
                        },
                    exchange_ts_ms=int(sample.server_ts_ms),
                    received_ts_ms=int(sample.receive_wall_ts_ms),
                    local_monotonic_ns=time.monotonic_ns(),
                    connection_id=None,
                    sequence=None,
                    provenance={
                        "access": "read_only",
                        "network": "mainnet",
                        "transport": "https",
                        "authenticated": False,
                        "real_execution": False,
                        "clock_probe": True,
                    },
                    parsed_summary={
                        "offset_ms": float(sample.offset_ms),
                        "rtt_ms": float(sample.rtt_ms),
                        "clock_offset_ms": float(sample.offset_ms),
                        "transport_rtt_ms": float(sample.rtt_ms),
                        "uncertainty_ms": uncertainty,
                        "data_gate_ready": False,
                    },
                )
                )
        except asyncio.CancelledError:
            raise
        except Exception:
            # Missing clock evidence must remain missing; raw market capture continues.
            sync.clear()

    async def probe_loop() -> None:
        while True:
            await asyncio.sleep(max(10.0, float(probe_interval_s)))
            await refresh_probe()

    async def refresh_bootstrap_capacity(
        requested_symbols: list[str] | None = None,
        *,
        expected_connection: str | None = None,
    ) -> None:
        bootstrap = getattr(client, "bootstrap_envelopes", None)
        if not callable(bootstrap):
            return
        subset = symbols if requested_symbols is None else requested_symbols
        try:
            bootstrap_rows = await asyncio.to_thread(bootstrap, subset)
        except asyncio.CancelledError:
            raise
        except Exception:
            # A failed REST rebootstrap must never revive uncertain Gate depth.
            if venue == "gate":
                if requested_symbols is None:
                    capacity_states.clear()
                else:
                    for symbol in requested_symbols:
                        capacity_states.pop(symbol, None)
            return
        # Never resurrect a snapshot requested during a previous WS connection.
        if expected_connection is not None and expected_connection != gate_connection_id:
            return
        for envelope in bootstrap_rows:
            await _emit_with_backpressure(sink, envelope)
            if venue == "gate" and envelope.channel == "l2Book":
                raw = (
                    dict(envelope.raw_payload)
                    if isinstance(envelope.raw_payload, Mapping)
                    else {}
                )
                # A successfully fetched official REST order_book with its
                # independent update id is a true full depth base, not a delta.
                raw["full"] = True
                raw["_alina_transport"] = {
                    "receive_wall_ts_ms": envelope.received_ts_ms,
                    "receive_mono_ns": envelope.local_monotonic_ns,
                    "connection_id": expected_connection or envelope.connection_id,
                }
                state = GateMarketState(contract=envelope.instrument)
                state.apply_book(raw, receive_ts_ms=envelope.received_ts_ms)
                if state.quality != "EXPLOITABLE" or state.sequence is None:
                    capacity_states.pop(envelope.instrument, None)
                    continue
                capacity_states[envelope.instrument] = state
                capacity = _capacity_from_native_state(
                    "gate",
                    state,
                    received_ts_ms=envelope.received_ts_ms,
                    timing_evidence=raw["_alina_transport"],
                    size_multiplier_to_base=capacity_multipliers.get(
                        envelope.instrument
                    ),
                )
                if capacity is not None:
                    await _emit_with_backpressure(sink, capacity)

    async def guarded_gate_rebootstrap(symbol: str, connection: str) -> None:
        # Serialize on-demand REST reads to avoid hammering Gate's public API.
        async with gate_refresh_slots:
            await refresh_bootstrap_capacity([symbol], expected_connection=connection)

    # Acquire explicit timing and official base-book evidence before admitting
    # incremental native frames.
    await refresh_probe()
    await refresh_bootstrap_capacity()
    probe_task = asyncio.create_task(probe_loop())
    connection_id = f"{venue}-{uuid.uuid4().hex}"
    try:
        async for payload in client.messages(symbols):
            receive_wall_ts_ms = int(time.time() * 1_000)
            receive_mono_ns = time.monotonic_ns()
            message = dict(payload)
            meta = message.get("_alina_transport")
            transport = dict(meta) if isinstance(meta, Mapping) else {}
            transport.setdefault("receive_wall_ts_ms", receive_wall_ts_ms)
            transport.setdefault("receive_mono_ns", receive_mono_ns)
            transport.setdefault("connection_id", connection_id)
            if venue == "gate":
                incoming_connection = str(transport.get("connection_id") or "") or None
                if gate_connection_id is None:
                    gate_connection_id = incoming_connection
                elif (
                    incoming_connection is not None
                    and incoming_connection != gate_connection_id
                ):
                    # Gate depth deltas require an authoritative base book.
                    # Rebootstrap immediately on a real websocket reconnect;
                    # if REST fails, refresh_bootstrap_capacity clears state
                    # and derived capacity stays fail-closed.
                    capacity_states.clear()
                    await refresh_bootstrap_capacity()
                    gate_connection_id = incoming_connection
            if sync:
                transport["clock_offset_ms"] = sync.get("offset_ms")
                transport["clock_probe_rtt_ms"] = sync.get("rtt_ms")
                transport["clock_probe_server_ts_ms"] = sync.get("server_ts_ms")
                transport["clock_probe_receive_wall_ts_ms"] = sync.get(
                    "probe_receive_wall_ts_ms"
                )
            message["_alina_transport"] = transport
            # Preserve each exchange trade identity even when a WS frame
            # contains a native batch. The existing splitter keeps provenance
            # and the original batch digest on every individual trade.
            for envelope in native_tick_envelopes(venue, message):
                await _emit_with_backpressure(sink, envelope)
            capacity = _native_capacity_envelope(
                venue,
                message,
                capacity_states,
                capacity_multipliers,
            )
            if capacity is not None:
                await _emit_with_backpressure(sink, capacity)
            if venue == "gate":
                result = message.get("result")
                contract = (
                    str(result.get("contract") or result.get("s") or "").upper()
                    if isinstance(result, Mapping) else ""
                )
                state = capacity_states.get(contract)
                if (
                    contract and isinstance(state, GateMarketState)
                    and state.reason in {"SEQUENCE_GAP", "SEQUENCE_REGRESSION"}
                    and gate_connection_id
                ):
                    # Raw WS frame was already written. Derived L2 stays dark
                    # until a new official REST book re-anchors this contract.
                    capacity_states.pop(contract, None)
                    now = time.monotonic()
                    pending = gate_refresh_tasks.get(contract)
                    if now >= gate_last_refresh_at.get(contract, 0.0) and (
                        pending is None or pending.done()
                    ):
                        gate_last_refresh_at[contract] = now + 30.0
                        gate_refresh_tasks[contract] = asyncio.create_task(
                            guarded_gate_rebootstrap(contract, gate_connection_id)
                        )
    finally:
        probe_task.cancel()
        for task in gate_refresh_tasks.values():
            task.cancel()
        await asyncio.gather(probe_task, *gate_refresh_tasks.values(), return_exceptions=True)


def _capacity_size_multiplier_from_metadata(
    venue: str,
    symbol: str,
    row: Mapping[str, Any],
) -> float | None:
    venue_key = str(venue).lower()
    if venue_key in {"hyperliquid", "binance", "bybit", "bitget"}:
        # Public USDT-linear depth size is already expressed in base-asset
        # quantity for these adapters. Bitget sizeMultiplier is a quantity step.
        return 1.0
    if venue_key == "gate":
        multiplier = _float(row.get("quanto_multiplier"))
        return multiplier if multiplier is not None and multiplier > 0 else None
    if venue_key == "okx":
        multiplier = _float(row.get("ctVal"))
        contract_value_ccy = str(row.get("ctValCcy") or "").upper()
        base_ccy = str(symbol).upper().split("-", 1)[0]
        if (
            multiplier is not None
            and multiplier > 0
            and contract_value_ccy == base_ccy
        ):
            return multiplier
    return None


async def _collect_instrument_metadata(
    venue_lists: Mapping[str, list[str]],
    sink: AsyncPartitionSink,
) -> dict[str, Any]:
    """Capture public replay-critical instrument rules at window start."""
    result: dict[str, Any] = {
        venue: {"records": 0, "status": "NO_DATA"}
        for venue in ("hyperliquid", "binance", "bybit", "okx", "gate", "bitget")
    }
    capacity_multipliers: dict[str, dict[str, float]] = {
        venue: {}
        for venue in ("hyperliquid", "binance", "bybit", "okx", "gate", "bitget")
    }

    hl_coins = {str(value).upper() for value in venue_lists.get("hyperliquid", [])}
    if hl_coins:
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.post(INFO_HYPERLIQUID, json={"type": "meta"})
                response.raise_for_status()
                payload = response.json()
            rows = payload.get("universe") if isinstance(payload, Mapping) else None
            receive_wall = int(time.time() * 1000)
            receive_mono = time.monotonic_ns()
            count = 0
            for row in rows if isinstance(rows, list) else []:
                if not isinstance(row, Mapping):
                    continue
                coin = str(row.get("name") or "").upper()
                if coin not in hl_coins:
                    continue
                capacity_multipliers["hyperliquid"][coin] = 1.0
                await _emit_with_backpressure(sink, 
                    TickEnvelope(
                        source_id="hyperliquid_public_rest",
                        channel="instrument_metadata",
                        instrument=coin,
                        event_kind=FeedEventKind.SNAPSHOT,
                        raw_payload=dict(row),
                        exchange_ts_ms=None,
                        received_ts_ms=receive_wall,
                        local_monotonic_ns=receive_mono,
                        connection_id=None,
                        sequence=None,
                        provenance={
                            "url": INFO_HYPERLIQUID,
                            "network": "mainnet",
                            "access": "read_only",
                            "transport": "https",
                            "authenticated": False,
                            "timestamp_semantics": "receive_observation_time_only",
                        },
                        parsed_summary={
                            "sz_decimals": row.get("szDecimals"),
                            "max_leverage": row.get("maxLeverage"),
                            "margin_table_id": row.get("marginTableId"),
                            "only_isolated": row.get("onlyIsolated"),
                            "is_delisted": row.get("isDelisted"),
                            "data_gate_ready": False,
                        },
                    )
                )
                count += 1
            result["hyperliquid"] = {"records": count, "status": "OK" if count else "NO_DATA"}
        except Exception as exc:
            result["hyperliquid"] = {"records": 0, "status": "ERROR", "error": type(exc).__name__}

    binance_symbols = {str(value).upper() for value in venue_lists.get("binance", [])}
    if binance_symbols:
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.get("https://fapi.binance.com/fapi/v1/exchangeInfo")
                response.raise_for_status()
                payload = response.json()
            rows = payload.get("symbols") if isinstance(payload, Mapping) else None
            receive_wall = int(time.time() * 1000)
            receive_mono = time.monotonic_ns()
            count = 0
            for row in rows if isinstance(rows, list) else []:
                if not isinstance(row, Mapping):
                    continue
                symbol = str(row.get("symbol") or "").upper()
                if symbol not in binance_symbols:
                    continue
                capacity_multipliers["binance"][symbol] = 1.0
                await _emit_with_backpressure(sink, 
                    TickEnvelope(
                        source_id="binance_usdm_public_rest",
                        channel="instrument_metadata",
                        instrument=symbol,
                        event_kind=FeedEventKind.SNAPSHOT,
                        raw_payload=dict(row),
                        exchange_ts_ms=None,
                        received_ts_ms=receive_wall,
                        local_monotonic_ns=receive_mono,
                        connection_id=None,
                        sequence=None,
                        provenance={
                            "url": "https://fapi.binance.com/fapi/v1/exchangeInfo",
                            "network": "mainnet",
                            "access": "read_only",
                            "transport": "https",
                            "authenticated": False,
                            "timestamp_semantics": "receive_observation_time_only",
                        },
                        parsed_summary={
                            "price_precision": row.get("pricePrecision"),
                            "quantity_precision": row.get("quantityPrecision"),
                            "filters": row.get("filters"),
                            "status": row.get("status"),
                            "data_gate_ready": False,
                        },
                    )
                )
                count += 1
            result["binance"] = {"records": count, "status": "OK" if count else "NO_DATA"}
        except Exception as exc:
            result["binance"] = {"records": 0, "status": "ERROR", "error": type(exc).__name__}

    clients: dict[str, Any] = {
        "bybit": BybitPublicClient(),
        "okx": OkxPublicClient(),
        "gate": GatePublicClient(),
        "bitget": BitgetPublicClient(),
    }
    for venue, client in clients.items():
        symbols = {str(value).upper() for value in venue_lists.get(venue, [])}
        if not symbols:
            continue
        try:
            if venue == "bybit":
                rows = await asyncio.to_thread(client.fetch_instrument_metadata)
            else:
                await asyncio.to_thread(client.discover_usdt_perpetuals)
                rows = list(getattr(client, "last_instrument_metadata", []) or [])
            try:
                server_ts = await asyncio.to_thread(client.server_time_ms)
            except Exception:
                server_ts = None
            receive_wall = int(time.time() * 1000)
            receive_mono = time.monotonic_ns()
            count = 0
            for row in rows:
                if not isinstance(row, Mapping):
                    continue
                if venue == "bybit":
                    symbol = str(row.get("symbol") or "").upper()
                elif venue == "okx":
                    symbol = str(row.get("instId") or "").upper()
                elif venue == "gate":
                    symbol = str(row.get("name") or row.get("contract") or "").upper()
                else:
                    symbol = str(row.get("symbol") or row.get("instId") or "").upper()
                if symbol not in symbols:
                    continue
                multiplier = _capacity_size_multiplier_from_metadata(
                    venue,
                    symbol,
                    row,
                )
                if multiplier is not None:
                    capacity_multipliers[venue][symbol] = multiplier
                envelope = native_instrument_metadata_envelope(
                    venue,
                    row,
                    received_ts_ms=receive_wall,
                    receive_mono_ns=receive_mono,
                    observed_server_ts_ms=server_ts,
                )
                if envelope is not None:
                    await _emit_with_backpressure(sink, envelope)
                    count += 1
            result[venue] = {"records": count, "status": "OK" if count else "NO_DATA"}
        except Exception as exc:
            result[venue] = {"records": 0, "status": "ERROR", "error": type(exc).__name__}
    for venue in result:
        result[venue]["capacity_size_multiplier_by_symbol"] = dict(
            capacity_multipliers[venue]
        )
    return result


async def _collect_funding_settlements(
    venue_lists: Mapping[str, list[str]],
    sink: AsyncPartitionSink,
    *,
    start_ms: int,
    end_ms: int,
) -> dict[str, dict[str, Any]]:
    """Backfill authoritative realized funding for the exact collection window.

    Every venue is isolated: one public API failure is visible in the summary and
    never becomes a synthetic zero-rate settlement.
    """
    specs = {
        "hyperliquid": (
            fetch_hyperliquid_funding_settlements,
            list(venue_lists.get("hyperliquid", [])),
        ),
        "binance": (
            fetch_binance_funding_settlements,
            list(venue_lists.get("binance", [])),
        ),
        "bybit": (
            fetch_bybit_funding_settlements,
            list(venue_lists.get("bybit", [])),
        ),
        "okx": (
            fetch_okx_funding_settlements,
            list(venue_lists.get("okx", [])),
        ),
        "gate": (
            fetch_gate_funding_settlements,
            list(venue_lists.get("gate", [])),
        ),
        "bitget": (
            fetch_bitget_funding_settlements,
            list(venue_lists.get("bitget", [])),
        ),
    }

    async def one(
        venue: str,
        fetcher: Any,
        symbols: list[str],
    ) -> tuple[str, dict[str, Any]]:
        if not symbols:
            return venue, {"status": "NO_DATA", "records": 0}
        try:
            rows = await fetcher(
                symbols,
                start_ms=int(start_ms),
                end_ms=int(end_ms),
            )
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            return venue, {
                "status": "ERROR",
                "records": 0,
                "error": type(exc).__name__,
            }
        for envelope in rows:
            await _emit_with_backpressure(sink, envelope)
        return venue, {
            "status": "OK" if rows else "NO_DATA",
            "records": len(rows),
        }

    result = await asyncio.gather(
        *(one(venue, fetcher, symbols) for venue, (fetcher, symbols) in specs.items())
    )
    return {venue: row for venue, row in result}


async def _native_bybit(
    symbols: list[str],
    sink: AsyncPartitionSink,
    *,
    session_refresh_s: float = 3600.0,
    capacity_size_multipliers: Mapping[str, float] | None = None,
) -> None:
    await _native_with_clock_sync(
        "bybit",
        BybitPublicClient(orderbook_depth=200, session_refresh_s=session_refresh_s),
        symbols,
        sink,
        capacity_size_multipliers=capacity_size_multipliers,
    )


async def _native_okx(
    symbols: list[str],
    sink: AsyncPartitionSink,
    *,
    session_refresh_s: float = 3600.0,
    capacity_size_multipliers: Mapping[str, float] | None = None,
) -> None:
    await _native_with_clock_sync(
        "okx",
        OkxPublicClient(session_refresh_s=session_refresh_s),
        symbols,
        sink,
        capacity_size_multipliers=capacity_size_multipliers,
    )


async def _hyperliquid(
    coins: list[str],
    sink: AsyncPartitionSink,
    *,
    clock_probe: HyperliquidClockSyncProbe | None = None,
) -> None:
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
                send_lock = asyncio.Lock()

                async def send_json(payload: Mapping[str, Any]) -> None:
                    async with send_lock:
                        await socket.send(json.dumps(dict(payload)))

                if clock_probe is not None:
                    clock_probe.mark_subscribe_sent()
                    await send_json(clock_probe.subscription_message())

                for coin in coins:
                    for channel in ("bbo", "l2Book", "trades", "activeAssetCtx"):
                        await send_json(
                            {
                                "method": "subscribe",
                                "subscription": {"type": channel, "coin": coin},
                            }
                        )

                async def heartbeat() -> None:
                    while True:
                        await asyncio.sleep(30.0)
                        await send_json({"method": "ping"})

                heartbeat_task = asyncio.create_task(heartbeat())
                try:
                    async for raw_text in socket:
                        receive_mono_ns = time.monotonic_ns()
                        receive_wall_ms = int(time.time() * 1_000)
                        try:
                            message = json.loads(raw_text)
                        except (TypeError, ValueError):
                            continue
                        if not isinstance(message, Mapping):
                            continue

                        if clock_probe is not None:
                            clock_probe.observe(
                                message,
                                received_wall_ts_ms=receive_wall_ms,
                            )
                            if clock_probe.refresh_due(now_ms=receive_wall_ms):
                                await send_json(clock_probe.unsubscribe_message())
                                clock_probe.mark_subscribe_sent(receive_wall_ms)
                                await send_json(clock_probe.subscription_message())

                        if message.get("channel") in {"subscriptionResponse", "pong"}:
                            continue

                        clock_evidence = (
                            clock_probe.evidence(now_ms=receive_wall_ms)
                            if clock_probe is not None
                            else None
                        )
                        for envelope in _hyperliquid_envelopes(
                            message,
                            received_ts_ms=receive_wall_ms,
                            receive_mono_ns=receive_mono_ns,
                            connection_id=connection_id,
                            clock_evidence=clock_evidence,
                        ):
                            envelope.reconnect_count = reconnects
                            await _emit_with_backpressure(sink, envelope)
                            if envelope.channel == "l2Book" and isinstance(message.get("data"), Mapping):
                                levels = message["data"].get("levels")
                                if isinstance(levels, list) and len(levels) >= 2:
                                    capacity = capacity_tape_envelope(
                                        venue="hyperliquid",
                                        instrument=envelope.instrument,
                                        bids=levels[0] if isinstance(levels[0], list) else [],
                                        asks=levels[1] if isinstance(levels[1], list) else [],
                                        exchange_ts_ms=envelope.exchange_ts_ms,
                                        received_ts_ms=envelope.received_ts_ms,
                                        receive_mono_ns=envelope.local_monotonic_ns,
                                        connection_id=envelope.connection_id,
                                        sequence=envelope.sequence,
                                        gap_count=envelope.gap_count,
                                        quality="EXPLOITABLE",
                                        timing_evidence=clock_evidence,
                                        source_raw_l2_payload=message,
                                    )
                                    if capacity is not None:
                                        capacity.reconnect_count = reconnects
                                        await _emit_with_backpressure(sink, capacity)
                finally:
                    heartbeat_task.cancel()
                    await asyncio.gather(heartbeat_task, return_exceptions=True)
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
    clock_probe: BinanceClockSyncProbe | None = None,
) -> None:
    if mode == "bbo":
        base = WS_BINANCE_PUBLIC
        suffix = "bookTicker"
        parser = _binance_bbo_envelope
    elif mode == "trades":
        base = WS_BINANCE_MARKET
        suffix = "trade"
        parser = _binance_trade_envelope
    elif mode == "agg_trades":
        base = WS_BINANCE_MARKET
        suffix = "aggTrade"
        parser = _binance_trade_envelope
    elif mode == "liquidations":
        base = WS_BINANCE_MARKET
        suffix = "forceOrder"
        parser = _binance_liquidation_envelope
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
                        clock_evidence=clock_probe.evidence() if clock_probe is not None else None,
                    )
                    if envelope is not None:
                        envelope.reconnect_count = reconnects
                        await _emit_with_backpressure(sink, envelope)
        except asyncio.CancelledError:
            raise
        except Exception:
            reconnects += 1
            await asyncio.sleep(min(30.0, 2.0 ** min(reconnects, 5)))


def _bundle_index(
    manifests: list[dict[str, Any]],
    *,
    collector_version: str,
    collection_run_id: str,
    queue_drops: Mapping[tuple[str, str, str], int],
) -> dict[str, Any]:
    return {
        "schema": V2_SCHEMA,
        "repository": V2_REPOSITORY,
        "collector_version": str(collector_version),
        "collection_run_id": str(collection_run_id),
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
            "gate": [f"{coin}_USDT" for coin in coins],
            "bitget": [f"{coin}USDT" for coin in coins],
        }
    result = {
        "hyperliquid": [],
        "binance": [],
        "bybit": [],
        "okx": [],
        "gate": [],
        "bitget": [],
    }
    for row in plan_rows:
        symbols = row["symbols"]
        for venue in result:
            symbol = symbols.get(venue)
            if symbol:
                result[venue].append(str(symbol))
    for venue in result:
        result[venue] = sorted(set(result[venue]))
    return result


def _l2_coverage_report(
    manifests: list[dict[str, Any]],
    venue_lists: Mapping[str, list[str]],
) -> dict[str, Any]:
    """Require one non-empty L2 shard for every expected venue/symbol."""
    expected = {
        venue: {str(symbol).upper() for symbol in symbols if str(symbol).strip()}
        for venue, symbols in venue_lists.items()
        if venue in L2_REQUIRED_VENUES and symbols
    }
    observed: dict[str, set[str]] = defaultdict(set)
    event_counts: dict[str, int] = defaultdict(int)
    for manifest in manifests:
        if str(manifest.get("family") or "") != "l2Book":
            continue
        venue = str(manifest.get("venue") or "").lower()
        symbol = str(manifest.get("symbol") or "").upper()
        events = int(manifest.get("event_count") or 0)
        if venue in expected and symbol and events > 0:
            observed[venue].add(symbol)
            event_counts[venue] += events

    missing = {
        venue: sorted(symbols - observed.get(venue, set()))
        for venue, symbols in expected.items()
        if symbols - observed.get(venue, set())
    }
    return {
        "required_venues": sorted(expected),
        "expected_symbol_count": sum(len(symbols) for symbols in expected.values()),
        "observed_symbol_count": sum(len(observed.get(venue, set())) for venue in expected),
        "event_count_by_venue": {
            venue: int(event_counts.get(venue, 0)) for venue in sorted(expected)
        },
        "missing_symbols": missing,
        "complete": not missing and bool(expected),
    }



def _replay_grade_coverage_report(
    manifests: list[dict[str, Any]],
    venue_lists: Mapping[str, list[str]],
) -> dict[str, Any]:
    """Verify actual persisted replay families, timing and clock proof."""
    required_by_venue: dict[str, set[str]] = {
        "hyperliquid": {"l2Book", "bbo", "trades", "capacity_tape", "instrument_metadata"},
        "binance": {"l2Book", "bbo", "agg_trades", "capacity_tape", "instrument_metadata"},
        "bybit": {"l2Book", "bbo", "trades", "ticker", "capacity_tape", "instrument_metadata"},
        "okx": {"l2Book", "bbo", "trades", "ticker", "capacity_tape", "instrument_metadata"},
        "gate": {"l2Book", "bbo", "trades", "ticker", "open_interest", "capacity_tape", "instrument_metadata"},
        "bitget": {"l2Book", "bbo", "trades", "ticker", "capacity_tape", "instrument_metadata"},
    }
    observed: dict[tuple[str, str], set[str]] = defaultdict(set)
    timing_defects: dict[str, dict[str, list[str]]] = defaultdict(lambda: defaultdict(list))
    trade_reconciliation_defects: dict[str, dict[str, list[str]]] = defaultdict(lambda: defaultdict(list))
    clock_sync_venues: set[str] = set()
    observed_cross_capacity_coins: set[str] = set()
    for manifest in manifests:
        venue = str(manifest.get("venue") or "").lower()
        symbol = str(manifest.get("symbol") or "").upper()
        family = str(manifest.get("family") or "")
        if family == "cross_venue_capacity_tape" and int(manifest.get("event_count") or 0) > 0:
            integrity = manifest.get("integrity")
            if isinstance(integrity, Mapping) and all(
                int(integrity.get(key) or 0) == 0
                for key in (
                    "missing_monotonic_count",
                    "missing_timestamp_count",
                    "gap_count",
                    "regression_count",
                    "duplicate_count",
                    "desync_count",
                )
            ) and manifest.get("replay_compatible") is not False:
                coin = canonical_coin(symbol)
                if coin:
                    observed_cross_capacity_coins.add(coin)
        if family == "clock_sync" and venue:
            clock_sync_venues.add(venue)
        if not venue or not symbol or int(manifest.get("event_count") or 0) <= 0:
            continue
        observed[(venue, symbol)].add(family)
        if family in {"l2Book", "bbo", "trades", "agg_trades", "capacity_tape"}:
            integrity = manifest.get("integrity")
            if isinstance(integrity, Mapping):
                defects = []
                if int(integrity.get("missing_monotonic_count") or 0) > 0:
                    defects.append("MISSING_MONOTONIC")
                if int(integrity.get("missing_timestamp_count") or 0) > 0:
                    defects.append("MISSING_TIMESTAMP")
                if int(integrity.get("gap_count") or 0) > 0:
                    defects.append("GAP")
                if int(integrity.get("regression_count") or 0) > 0:
                    defects.append("REGRESSION")
                if int(integrity.get("duplicate_count") or 0) > 0:
                    defects.append("DUPLICATES")
                if int(integrity.get("desync_count") or 0) > 0:
                    defects.append("DESYNC")
                if manifest.get("replay_compatible") is False:
                    defects.append("REPLAY_NOT_VERIFIED")
                if defects:
                    timing_defects[venue][symbol].extend(defects)
        if family in {"trades", "agg_trades"}:
            reconciliation = manifest.get("reconciliation")
            status = (
                str(reconciliation.get("status") or "UNVERIFIED").upper()
                if isinstance(reconciliation, Mapping)
                else "UNVERIFIED"
            )
            if status != "MATCHED":
                trade_reconciliation_defects[venue][symbol].append(status)

    per_venue: dict[str, Any] = {}
    all_complete = True
    for venue, symbols in venue_lists.items():
        if not symbols:
            continue
        required = required_by_venue.get(venue, {"l2Book", "instrument_metadata"})
        missing: dict[str, list[str]] = {}
        for symbol in sorted({str(value).upper() for value in symbols if str(value).strip()}):
            absent = sorted(required - observed.get((venue, symbol), set()))
            if absent:
                missing[symbol] = absent
        timing = {
            symbol: sorted(set(reasons))
            for symbol, reasons in sorted(timing_defects.get(venue, {}).items())
            if reasons
        }
        trade_reconciliation = {
            symbol: sorted(set(reasons))
            for symbol, reasons in sorted(trade_reconciliation_defects.get(venue, {}).items())
            if reasons
        }
        clock_required = venue in {"bybit", "okx", "gate", "bitget"}
        clock_ok = venue in clock_sync_venues if clock_required else True
        complete = not missing and not timing and not trade_reconciliation and clock_ok
        all_complete = all_complete and complete
        per_venue[venue] = {
            "required_families": sorted(required),
            "missing_families_by_symbol": missing,
            "timing_defects_by_symbol": timing,
            "trade_reconciliation_defects_by_symbol": trade_reconciliation,
            "clock_sync_required": clock_required,
            "clock_sync_observed": clock_ok,
            "complete": complete,
        }
    expected_coin_venues: dict[str, set[str]] = defaultdict(set)
    for venue, symbols in venue_lists.items():
        for symbol in symbols:
            coin = canonical_coin(str(symbol))
            if coin:
                expected_coin_venues[coin].add(str(venue).lower())
    expected_cross_capacity_coins = {
        coin for coin, venues in expected_coin_venues.items() if len(venues) >= 2
    }
    missing_cross_capacity_coins = sorted(
        expected_cross_capacity_coins - observed_cross_capacity_coins
    )
    return {
        "schema": "alina.replay_grade_coverage.v1",
        "per_venue": per_venue,
        "complete": all_complete and bool(per_venue) and not missing_cross_capacity_coins,
        "cross_venue_capacity_coins_observed": sorted(observed_cross_capacity_coins),
        "missing_cross_venue_capacity_coins": missing_cross_capacity_coins,
        "liquidation_families_observed": sorted(
            {
                str(manifest.get("venue") or "").lower()
                for manifest in manifests
                if str(manifest.get("family") or "") == "liquidations"
                and int(manifest.get("event_count") or 0) > 0
            }
        ),
        "fail_closed": True,
    }

def _l2_gate_failure_reason(
    coverage: Mapping[str, Any],
    *,
    required: bool,
) -> str | None:
    """Fail globally only when required L2 collection produced no usable L2 at all.

    Per-venue/per-symbol misses remain explicit in the coverage receipt and are
    blocked downstream by dependency closure instead of stopping unrelated healthy
    collection streams.
    """
    if not required:
        return None
    expected = int(coverage.get("expected_symbol_count") or 0)
    observed = int(coverage.get("observed_symbol_count") or 0)
    if expected <= 0:
        return "L2_EXPECTATION_EMPTY"
    if observed <= 0:
        return "L2_COLLECTION_EMPTY"
    return None


async def collect(
    output: Path,
    *,
    coins: list[str],
    duration_s: float,
    collector_version: str,
    rotate_bytes: int,
    plan_rows: list[dict[str, Any]] | None = None,
    collection_run_id: str | None = None,
    min_free_disk_bytes: int = 2 * 1024 * 1024 * 1024,
    require_l2: bool = False,
) -> dict[str, Any]:
    raw_root = output / "raw"
    assets_root = output / "assets"
    manifests_root = output / "manifests"
    assets_root.mkdir(parents=True, exist_ok=True)
    manifests_root.mkdir(parents=True, exist_ok=True)

    writer = PartitionedTickDatasetWriter(
        raw_root,
        rotate_bytes=rotate_bytes,
        # Raw JSONL is fsynced on every append_batch_records() call. Rewriting
        # the *whole* shard-index sidecar for every partition batch scales
        # quadratically as shards accumulate, stalls the consumer and drives
        # queue backpressure / dropped frames. Refresh the sidecar less often;
        # the final rotate_all() still seals every immutable gzip shard.
        flush_every=128,
    )
    sink = AsyncPartitionSink(writer)
    writer_task = asyncio.create_task(sink.run())

    venue_lists = _venue_lists(coins, plan_rows)
    hl_coins = venue_lists["hyperliquid"]
    bybit_symbols = venue_lists["bybit"]
    okx_symbols = venue_lists["okx"]
    binance_symbols = venue_lists["binance"]
    gate_symbols = venue_lists["gate"]
    bitget_symbols = venue_lists["bitget"]

    instrument_metadata = await _collect_instrument_metadata(venue_lists, sink)
    capacity_size_multipliers = {
        venue: dict(
            (instrument_metadata.get(venue) or {}).get(
                "capacity_size_multiplier_by_symbol"
            )
            or {}
        )
        for venue in ("hyperliquid", "binance", "bybit", "okx", "gate", "bitget")
    }
    native_session_refresh_s = max(3600.0, float(duration_s) + 300.0)

    hyperliquid_clock = HyperliquidClockSyncProbe() if hl_coins else None
    binance_clock = BinanceClockSyncProbe() if binance_symbols else None
    binance_depth = BinanceDepthLiveCollector(
        binance_symbols,
        # Await bounded queue for Binance L2; no silent sync frame drops.
        tick_sink=sink.emit_async,
        publication_depth=200,
        snapshot_limit=1000,
        clock_sync_provider=(binance_clock.evidence if binance_clock is not None else None),
    )
    binance_context = BinanceMarketContextCollector(
        binance_symbols,
        tick_sink=sink.emit_async,
        clock_sync_provider=(binance_clock.evidence if binance_clock is not None else None),
    )
    hyperliquid_trade_reference = (
        HyperliquidTradeReferenceSampler(
            hl_coins,
            info_url=INFO_HYPERLIQUID,
            interval_s=5.0,
        )
        if hl_coins
        else None
    )

    tasks: list[asyncio.Task[Any]] = []
    if bybit_symbols:
        tasks.append(
            asyncio.create_task(
                _native_bybit(
                    bybit_symbols,
                    sink,
                    session_refresh_s=native_session_refresh_s,
                    capacity_size_multipliers=capacity_size_multipliers["bybit"],
                )
            )
        )
    if okx_symbols:
        tasks.append(
            asyncio.create_task(
                _native_okx(
                    okx_symbols,
                    sink,
                    session_refresh_s=native_session_refresh_s,
                    capacity_size_multipliers=capacity_size_multipliers["okx"],
                )
            )
        )
    if gate_symbols:
        tasks.append(
            asyncio.create_task(
                _native_with_clock_sync(
                    "gate",
                    GatePublicClient(session_refresh_s=native_session_refresh_s),
                    gate_symbols,
                    sink,
                    capacity_size_multipliers=capacity_size_multipliers["gate"],
                )
            )
        )
    if bitget_symbols:
        tasks.append(
            asyncio.create_task(
                _native_with_clock_sync(
                    "bitget",
                    BitgetPublicClient(session_refresh_s=native_session_refresh_s),
                    bitget_symbols,
                    sink,
                    capacity_size_multipliers=capacity_size_multipliers["bitget"],
                )
            )
        )
    if hl_coins:
        tasks.append(
            asyncio.create_task(
                _hyperliquid(
                    hl_coins,
                    sink,
                    clock_probe=hyperliquid_clock,
                )
            )
        )
        if hyperliquid_trade_reference is not None:
            tasks.append(asyncio.create_task(hyperliquid_trade_reference.run()))
    if binance_symbols:
        tasks.extend(
            (
                asyncio.create_task(binance_clock.run()) if binance_clock is not None else asyncio.create_task(asyncio.sleep(0)),
                asyncio.create_task(_binance_stream(binance_symbols, sink, mode="bbo", clock_probe=binance_clock)),
                asyncio.create_task(_binance_stream(binance_symbols, sink, mode="trades", clock_probe=binance_clock)),
                asyncio.create_task(_binance_stream(binance_symbols, sink, mode="agg_trades", clock_probe=binance_clock)),
                asyncio.create_task(_binance_stream(binance_symbols, sink, mode="liquidations", clock_probe=binance_clock)),
                asyncio.create_task(binance_depth.run()),
                asyncio.create_task(binance_context.run()),
            )
        )
    if not tasks:
        raise RuntimeError("collection plan contains no supported venue streams")
    started = int(time.time() * 1_000)
    run_id = str(collection_run_id or "").strip() or (
        f"market-{str(collector_version)[:12]}-{started}"
    )
    funding_history: dict[str, dict[str, Any]] = {}
    stop_event = asyncio.Event()
    stop_reason = "DURATION_REACHED"
    disk_free_bytes_at_stop: int | None = None

    async def duration_guard() -> None:
        nonlocal stop_reason
        await asyncio.sleep(max(1.0, float(duration_s)))
        stop_reason = "DURATION_REACHED"
        stop_event.set()

    async def disk_guard() -> None:
        nonlocal stop_reason, disk_free_bytes_at_stop
        threshold = max(0, int(min_free_disk_bytes))
        if threshold <= 0:
            return
        while not stop_event.is_set():
            usage = await asyncio.to_thread(shutil.disk_usage, output)
            disk_free_bytes_at_stop = int(usage.free)
            if int(usage.free) < threshold:
                stop_reason = "LOW_DISK_SPACE"
                stop_event.set()
                return
            try:
                await asyncio.wait_for(stop_event.wait(), timeout=15.0)
            except TimeoutError:
                pass

    guard_tasks = [
        asyncio.create_task(duration_guard()),
        asyncio.create_task(disk_guard()),
    ]
    try:
        await stop_event.wait()
    finally:
        for guard in guard_tasks:
            guard.cancel()
        await asyncio.gather(*guard_tasks, return_exceptions=True)
        ended_for_funding = int(time.time() * 1_000)
        # Final independent REST sample while the live websocket window is still
        # open, so reference coverage includes the tail of the capture.
        if hyperliquid_trade_reference is not None:
            await hyperliquid_trade_reference.sample_once()
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        if binance_clock is not None:
            await binance_clock.close()
        funding_history = await _collect_funding_settlements(
            venue_lists,
            sink,
            start_ms=started,
            end_ms=ended_for_funding,
        )
        if hyperliquid_trade_reference is not None:
            await hyperliquid_trade_reference.close()
        await sink.close()
        await writer_task

    shards = await asyncio.to_thread(writer.rotate_all)
    manifests: list[dict[str, Any]] = []
    shard_preliminaries: list[tuple[Path, dict[str, Any]]] = []
    for shard in shards:
        manifest = await asyncio.to_thread(
            build_manifest_from_tick_shard,
            shard,
            collector_version=collector_version,
            reconciliation_status="UNVERIFIED",
        )
        shard_preliminaries.append((shard, manifest))
    drop_attribution = attribute_queue_drops(
        [manifest for _shard, manifest in shard_preliminaries],
        sink.drops,
        sink.drop_windows,
        timestamps_are_ms=True,
    )
    orphan_drops = orphaned_queue_drops(
        [manifest for _shard, manifest in shard_preliminaries], sink.drops,
    )
    for (shard, manifest), drops in zip(shard_preliminaries, drop_attribution):
        if drops:
            manifest["integrity"]["gap_count"] = (
                int(manifest["integrity"].get("gap_count") or 0) + drops
            )
            manifest["collection_queue_drops"] = drops
            manifest["queue_drop_attribution_method"] = "connection_receive_millisecond_v2"
        manifest["collection_run_id"] = run_id
        manifest = finalize_manifest(manifest)

        asset_name = f"{manifest['dataset_id']}.jsonl.gz"
        asset_path = assets_root / asset_name
        shutil.move(str(shard), asset_path)
        manifest["release_asset"] = asset_name
        manifest["bytes"] = asset_path.stat().st_size

        family = str(manifest.get("family") or "")
        if family in {"trades", "agg_trades"}:
            venue = str(manifest.get("venue") or "").lower()
            sync = manifest.get("synchronization")
            sync_map = sync if isinstance(sync, Mapping) else {}
            reference_start = (
                _int(sync_map.get("first_exchange_ts_ms"))
                or _int(manifest.get("start_ts_ms"))
                or 0
            )
            reference_end = (
                _int(sync_map.get("last_exchange_ts_ms"))
                or _int(manifest.get("end_ts_ms"))
                or reference_start
            )
            if venue == "bybit" and family == "trades":
                report = await reconcile_bybit_trade_shard(
                    asset_path,
                    symbol=str(manifest.get("symbol") or ""),
                    start_ms=reference_start,
                    end_ms=reference_end,
                )
                manifest = attach_reconciliation(manifest, report)
            elif venue == "okx" and family == "trades":
                report = await reconcile_okx_trade_shard(
                    asset_path,
                    symbol=str(manifest.get("symbol") or ""),
                    start_ms=reference_start,
                    end_ms=reference_end,
                )
                manifest = attach_reconciliation(manifest, report)
            elif (
                venue == "hyperliquid"
                and family == "trades"
                and hyperliquid_trade_reference is not None
            ):
                report = hyperliquid_trade_reference.reconcile(
                    asset_path,
                    symbol=str(manifest.get("symbol") or ""),
                    start_ms=reference_start,
                    end_ms=reference_end,
                )
                manifest = attach_reconciliation(manifest, report)
            elif venue == "binance" and family == "agg_trades":
                report = await reconcile_binance_aggtrade_shard(
                    asset_path,
                    symbol=str(manifest.get("symbol") or ""),
                    start_ms=reference_start,
                    end_ms=reference_end,
                )
                manifest = attach_reconciliation(manifest, report)
            elif venue == "gate" and family == "trades":
                report = await reconcile_gate_trade_shard(
                    asset_path,
                    symbol=str(manifest.get("symbol") or ""),
                    start_ms=reference_start,
                    end_ms=reference_end,
                )
                manifest = attach_reconciliation(manifest, report)
            elif venue == "bitget" and family == "trades":
                report = await reconcile_bitget_trade_shard(
                    asset_path,
                    symbol=str(manifest.get("symbol") or ""),
                    start_ms=reference_start,
                    end_ms=reference_end,
                )
                manifest = attach_reconciliation(manifest, report)
            else:
                manifest = attach_reconciliation(
                    manifest,
                    {
                        "status": "UNAVAILABLE",
                        "reason": "NO_EXACT_PUBLIC_TRADE_REFERENCE",
                    },
                )

        manifest_path = manifests_root / f"{manifest['dataset_id']}.json"
        write_manifest(manifest, manifest_path)
        manifests.append(manifest)

    l2_coverage = _l2_coverage_report(manifests, venue_lists)
    replay_grade_coverage = _replay_grade_coverage_report(manifests, venue_lists)

    bundle_index = _bundle_index(
        manifests,
        collector_version=collector_version,
        collection_run_id=run_id,
        queue_drops=sink.drops,
    )
    bundle_index["l2_coverage"] = {
        **l2_coverage,
        "required": bool(require_l2),
    }
    bundle_index["replay_grade_coverage"] = replay_grade_coverage
    bundle_index["unattributed_queue_drops"] = orphan_drops
    bundle_index["collection_window_integrity_verified"] = not any(sink.drops.values())
    write_manifest(bundle_index, output / "BUNDLE_INDEX.json")

    summary = {
        "schema": "alina.cloud_collection_window.v1",
        "started_at_ms": started,
        "ended_at_ms": int(time.time() * 1_000),
        "duration_s": round((int(time.time() * 1_000) - started) / 1000.0, 3),
        "coins": coins,
        "venue_symbols": venue_lists,
        "collector_version": collector_version,
        "collection_run_id": run_id,
        "stop_reason": stop_reason,
        "min_free_disk_bytes": max(0, int(min_free_disk_bytes)),
        "disk_free_bytes_at_stop": disk_free_bytes_at_stop,
        "accepted_frames": sink.accepted,
        "persisted_frames": sink.persisted,
        "backpressure_events": sink.backpressure_events,
        "unattributed_queue_drops": orphan_drops,
        "queue_drops": {
            "|".join(key): value for key, value in sorted(sink.drops.items())
        },
        "asset_count": len(manifests),
        "l2_coverage": {
            **l2_coverage,
            "required": bool(require_l2),
        },
        "replay_grade_coverage": replay_grade_coverage,
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
        "instrument_metadata": instrument_metadata,
        "hyperliquid_clock_sync": (
            hyperliquid_clock.health()
            if hyperliquid_clock is not None
            else {"status": "NO_DATA"}
        ),
        "binance_clock_sync": (
            binance_clock.health() if binance_clock is not None else {"status": "NO_DATA"}
        ),
        "binance_depth": binance_depth.health(),
        "binance_context": binance_context.health(),
        "funding_history": funding_history,
        "hyperliquid_trade_reference": (
            hyperliquid_trade_reference.stats()
            if hyperliquid_trade_reference is not None
            else None
        ),
        "read_only": True,
        "real_execution": False,
    }
    (output / "collection_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    l2_failure = _l2_gate_failure_reason(l2_coverage, required=bool(require_l2))
    if l2_failure is not None:
        raise RuntimeError(
            l2_failure + ":" + json.dumps(l2_coverage["missing_symbols"], sort_keys=True)
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
    parser.add_argument("--collection-run-id")
    parser.add_argument("--rotate-mb", type=int, default=64)
    parser.add_argument(
        "--require-l2",
        action="store_true",
        help="Fail closed unless every expected venue/symbol produced non-empty l2Book data.",
    )
    parser.add_argument(
        "--min-free-disk-gb",
        type=float,
        default=2.0,
        help="Seal and publish early if free runner disk falls below this threshold; 0 disables.",
    )
    args = parser.parse_args()

    plan_path = Path(args.plan_file) if args.plan_file else None
    plan_rows = _load_plan_rows(plan_path) if plan_path else None
    if plan_path is not None:
        output_root = Path(args.output)
        output_root.mkdir(parents=True, exist_ok=True)
        plan_bytes = plan_path.read_bytes()
        (output_root / "collection_plan.json").write_bytes(plan_bytes)
        (output_root / "collection_plan.sha256").write_text(
            hashlib.sha256(plan_bytes).hexdigest() + "\n",
            encoding="utf-8",
        )
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
            collection_run_id=args.collection_run_id,
            min_free_disk_bytes=max(0, int(float(args.min_free_disk_gb) * 1024**3)),
            require_l2=bool(args.require_l2),
        )
    )
    print(json.dumps(summary, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
