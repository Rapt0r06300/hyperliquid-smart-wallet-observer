"""Bitget USDT futures public collector (read-only)."""
from __future__ import annotations

import asyncio
import json
import time
import uuid
from collections.abc import AsyncIterator, Iterable, Mapping
from dataclasses import dataclass, field
from typing import Any

import httpx
import websockets

from hl_observer.collection.backoff import compute_backoff_delay
from hl_observer.collection.feed_integrity import estimate_clock_sync
from hl_observer.collection.market_capture_tiers import CaptureTier, capture_profile
from hl_observer.collection.native_venue_market import (
    DESYNC,
    EXPLOITABLE,
    UNMEASURABLE,
    MarketLevel,
    NativeMarketSnapshot,
    canonical_coin,
)

REST_BASE_URL = "https://api.bitget.com"
PUBLIC_WS_URL = "wss://ws.bitget.com/v2/ws/public"
PUBLIC_UTA_WS_URL = "wss://ws.bitget.com/v3/ws/public"


def _f(v: Any) -> float | None:
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _i(v: Any) -> int | None:
    try:
        return int(v)
    except (TypeError, ValueError):
        return None


def parse_bitget_instruments(payload: dict[str, Any]) -> list[tuple[str, str]]:
    out = []
    for x in payload.get("data", []) if isinstance(payload, dict) else []:
        if (
            not isinstance(x, dict)
            or str(x.get("quoteCoin", "")).upper() != "USDT"
            or str(x.get("symbolStatus", "normal")).lower() not in {"normal", "listed"}
        ):
            continue
        symbol = str(x.get("symbol") or "").upper()
        base = str(x.get("baseCoin") or canonical_coin(symbol)).upper()
        if symbol and base:
            out.append((base, symbol))
    return sorted(set(out))


@dataclass(slots=True)
class BitgetMarketState:
    symbol: str
    stale_after_ms: int = 1000
    bids: dict[float, float] = field(default_factory=dict)
    asks: dict[float, float] = field(default_factory=dict)
    sequence: int | None = None
    exchange_ts_ms: int = 0
    receive_ts_ms: int = 0
    quality: str = UNMEASURABLE
    reason: str = "NO_SNAPSHOT"
    last: float | None = None
    mark: float | None = None
    index: float | None = None
    volume_24h: float | None = None
    open_interest: float | None = None
    funding_rate: float | None = None
    receive_mono_ns: int | None = None
    connection_id: str | None = None
    transport_rtt_ms: float | None = None
    clock_offset_ms: float | None = None
    gap_count: int = 0
    regression_count: int = 0

    def apply(self, payload: dict[str, Any], *, receive_ts_ms: int | None = None) -> str:
        arg = payload.get("arg") or {}
        data = payload.get("data") or []
        item = data[0] if data and isinstance(data[0], dict) else {}
        meta = payload.get("_alina_transport")
        transport = dict(meta) if isinstance(meta, Mapping) else {}
        if str(arg.get("instId") or self.symbol).upper() != self.symbol.upper():
            self.quality, self.reason = DESYNC, "SYMBOL_MISMATCH"
            return self.quality
        channel = str(arg.get("channel", "")).lower()
        if channel in {"books", "books1", "books5", "books15"}:
            seq = _i(item.get("seq") or item.get("seqId"))
            prev = _i(item.get("pseq") or item.get("prevSeqId"))
            action = str(payload.get("action") or "").lower()
            snapshot_push = action == "snapshot" or channel in {"books1", "books5", "books15"}

            if not snapshot_push and self.sequence is not None and seq is not None:
                if prev is not None and prev != self.sequence:
                    self.gap_count += 1
                    self.bids.clear()
                    self.asks.clear()
                    self.quality, self.reason = DESYNC, "SEQUENCE_GAP"
                    return self.quality
                if seq < self.sequence:
                    self.regression_count += 1
                    self.bids.clear()
                    self.asks.clear()
                    self.quality, self.reason = DESYNC, "SEQUENCE_REGRESSION"
                    return self.quality

            if snapshot_push:
                next_bids: dict[float, float] = {}
                next_asks: dict[float, float] = {}
                targets = ((item.get("bids"), next_bids), (item.get("asks"), next_asks))
            else:
                targets = ((item.get("bids"), self.bids), (item.get("asks"), self.asks))

            for raw, target in targets:
                for row in raw or []:
                    if not isinstance(row, (list, tuple)) or len(row) < 2:
                        continue
                    price, size = _f(row[0]), _f(row[1])
                    if price is None or price <= 0 or size is None:
                        continue
                    if size <= 0:
                        target.pop(price, None)
                    else:
                        target[price] = size

            if snapshot_push:
                self.bids = next_bids
                self.asks = next_asks
            self.sequence = seq if seq is not None else self.sequence
            self.quality = (
                EXPLOITABLE
                if self.bids and self.asks and max(self.bids) <= min(self.asks)
                else UNMEASURABLE
            )
            self.reason = "" if self.quality == EXPLOITABLE else "INVALID_BBO"
        self.exchange_ts_ms = _i(item.get("ts")) or self.exchange_ts_ms
        self.receive_ts_ms = receive_ts_ms or _i(transport.get("receive_wall_ts_ms")) or int(time.time() * 1000)
        self.receive_mono_ns = _i(transport.get("receive_mono_ns")) or self.receive_mono_ns
        self.connection_id = str(transport.get("connection_id") or "") or self.connection_id
        if transport.get("transport_rtt_ms") is not None:
            self.transport_rtt_ms = _f(transport.get("transport_rtt_ms"))
        if transport.get("clock_offset_ms") is not None:
            self.clock_offset_ms = _f(transport.get("clock_offset_ms"))
        self.last = _f(item.get("lastPr") or item.get("lastPrice")) or self.last
        self.mark = _f(item.get("markPrice")) or self.mark
        self.index = _f(item.get("indexPrice")) or self.index
        if item.get("fundingRate") is not None:
            self.funding_rate = _f(item.get("fundingRate"))
        self.open_interest = _f(item.get("holdingAmount")) or self.open_interest
        return self.quality

    def snapshot(self, *, now_ms: int | None = None) -> NativeMarketSnapshot:
        bids = tuple(MarketLevel(p, s) for p, s in sorted(self.bids.items(), reverse=True))
        asks = tuple(MarketLevel(p, s) for p, s in sorted(self.asks.items()))
        return NativeMarketSnapshot.build(
            venue="bitget",
            coin=canonical_coin(self.symbol),
            exchange_symbol=self.symbol,
            bid=bids[0].price if bids else 0,
            ask=asks[0].price if asks else 0,
            bids=bids,
            asks=asks,
            exchange_ts_ms=self.exchange_ts_ms,
            receive_ts_ms=self.receive_ts_ms,
            now_ms=now_ms,
            stale_after_ms=self.stale_after_ms,
            quality=self.quality if self.quality in {DESYNC, UNMEASURABLE} else None,
            last=self.last,
            mark=self.mark,
            index=self.index,
            open_interest=self.open_interest,
            funding_rate=self.funding_rate,
            sequence=self.sequence,
            connection_id=self.connection_id,
            receive_mono_ns=self.receive_mono_ns,
            transport_rtt_ms=self.transport_rtt_ms,
            clock_offset_ms=self.clock_offset_ms,
            gap_count=self.gap_count,
            regression_count=self.regression_count,
            reason=self.reason,
        )


class BitgetPublicClient:
    def __init__(
        self,
        *,
        rest_base_url: str = REST_BASE_URL,
        ws_url: str = PUBLIC_WS_URL,
        uta_ws_url: str = PUBLIC_UTA_WS_URL,
        session_refresh_s: float = 900.0,
    ) -> None:
        self.rest_base_url = rest_base_url.rstrip("/")
        self.ws_url = ws_url
        self.uta_ws_url = uta_ws_url
        self.session_refresh_s = max(60.0, float(session_refresh_s))
        self.capture_tier = CaptureTier.B
        self.capture_tiers_by_symbol: dict[str, CaptureTier] = {}
        self.last_instrument_metadata: list[dict[str, Any]] = []

    def set_capture_profile(self, tier: CaptureTier | str) -> None:
        self.capture_tier = capture_profile("bitget", tier).tier

    def set_capture_profiles(self, tiers: Mapping[str, CaptureTier | str]) -> None:
        self.capture_tiers_by_symbol = {
            str(symbol).upper(): capture_profile("bitget", tier).tier
            for symbol, tier in tiers.items()
        }

    def subscription_args(self, symbols: Iterable[str]) -> list[dict[str, str]]:
        return [
            {"instType": "USDT-FUTURES", "channel": channel, "instId": symbol}
            for symbol in sorted({str(s).upper() for s in symbols if str(s).strip()})
            for channel in capture_profile(
                "bitget", self.capture_tiers_by_symbol.get(symbol, self.capture_tier)
            ).channels
            if channel != "liquidation"
        ]

    def discover_usdt_perpetuals(self, *, timeout_s: float = 10.0):
        with httpx.Client(timeout=timeout_s) as client:
            response = client.get(
                f"{self.rest_base_url}/api/v2/mix/market/contracts",
                params={"productType": "USDT-FUTURES"},
            )
            response.raise_for_status()
            payload = response.json()
        data = payload.get("data") if isinstance(payload, dict) else None
        self.last_instrument_metadata = [dict(row) for row in (data or []) if isinstance(row, dict)]
        return parse_bitget_instruments(payload)

    def server_time_ms(self, *, timeout_s: float = 5.0) -> int:
        with httpx.Client(timeout=timeout_s) as client:
            response = client.get(f"{self.rest_base_url}/api/v2/public/time")
            response.raise_for_status()
            payload = response.json()
        data = payload.get("data") if isinstance(payload, Mapping) else None
        server = _i(data.get("serverTime")) if isinstance(data, Mapping) else None
        if server is None:
            raise RuntimeError("Bitget server time missing")
        return server

    def measure_clock_sync(self, *, timeout_s: float = 5.0):
        sent = int(time.time() * 1000)
        server = self.server_time_ms(timeout_s=timeout_s)
        received = int(time.time() * 1000)
        return estimate_clock_sync(
            venue="bitget",
            server_ts_ms=server,
            send_wall_ts_ms=sent,
            receive_wall_ts_ms=received,
        )

    async def _classic_messages(self, symbols: tuple[str, ...]) -> AsyncIterator[dict[str, Any]]:
        args = self.subscription_args(symbols)
        attempt = 0
        while True:
            try:
                connection_id = f"bitget-v2-{uuid.uuid4().hex}"
                session_started = time.monotonic()
                async with websockets.connect(self.ws_url, ping_interval=20, ping_timeout=10) as socket:
                    await socket.send(json.dumps({"op": "subscribe", "args": args}))
                    attempt = 0
                    async for raw in socket:
                        receive_mono_ns = time.monotonic_ns()
                        receive_wall_ts_ms = int(time.time() * 1000)
                        if raw == "pong":
                            continue
                        payload = json.loads(raw)
                        if not isinstance(payload, dict):
                            continue
                        latency = getattr(socket, "latency", None)
                        payload["_alina_transport"] = {
                            "connection_id": connection_id,
                            "receive_wall_ts_ms": receive_wall_ts_ms,
                            "receive_mono_ns": receive_mono_ns,
                            "transport_rtt_ms": float(latency) * 1000.0 if isinstance(latency, (int, float)) else None,
                        }
                        yield payload
                        if time.monotonic() - session_started >= self.session_refresh_s:
                            return
            except asyncio.CancelledError:
                raise
            except Exception:
                delay = compute_backoff_delay(attempt=attempt, shard_key="bitget-v2-public-ws")
                attempt += 1
                await asyncio.sleep(delay.delay_seconds)

    async def _uta_liquidation_messages(self, symbols: tuple[str, ...]) -> AsyncIterator[dict[str, Any]]:
        wanted = set(symbols)
        attempt = 0
        while True:
            try:
                connection_id = f"bitget-v3-liq-{uuid.uuid4().hex}"
                session_started = time.monotonic()
                async with websockets.connect(self.uta_ws_url, ping_interval=20, ping_timeout=10) as socket:
                    await socket.send(
                        json.dumps(
                            {
                                "op": "subscribe",
                                "args": [{"instType": "usdt-futures", "topic": "liquidation"}],
                            }
                        )
                    )
                    attempt = 0
                    async for raw in socket:
                        receive_mono_ns = time.monotonic_ns()
                        receive_wall_ts_ms = int(time.time() * 1000)
                        if raw == "pong":
                            continue
                        payload = json.loads(raw)
                        if not isinstance(payload, dict):
                            continue
                        data = payload.get("data")
                        rows = [row for row in data if isinstance(row, Mapping)] if isinstance(data, list) else []
                        for row in rows:
                            symbol = str(row.get("symbol") or "").upper()
                            if symbol not in wanted:
                                continue
                            yield {
                                "arg": {
                                    "instType": "USDT-FUTURES",
                                    "channel": "liquidation",
                                    "instId": symbol,
                                },
                                "data": [dict(row)],
                                "ts": row.get("ts"),
                                "_alina_transport": {
                                    "connection_id": connection_id,
                                    "receive_wall_ts_ms": receive_wall_ts_ms,
                                    "receive_mono_ns": receive_mono_ns,
                                    "transport_rtt_ms": None,
                                    "source_ws": "bitget_uta_v3_public",
                                },
                            }
                        if time.monotonic() - session_started >= self.session_refresh_s:
                            return
            except asyncio.CancelledError:
                raise
            except Exception:
                delay = compute_backoff_delay(attempt=attempt, shard_key="bitget-v3-liquidation-ws")
                attempt += 1
                await asyncio.sleep(delay.delay_seconds)

    async def messages(self, symbols: Iterable[str]) -> AsyncIterator[dict[str, Any]]:
        symbols_tuple = tuple(sorted({str(s).upper() for s in symbols if str(s).strip()}))
        if not symbols_tuple:
            return
        queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue(maxsize=10000)

        async def pump(iterator: AsyncIterator[dict[str, Any]]) -> None:
            async for item in iterator:
                await queue.put(item)

        tasks = [
            asyncio.create_task(pump(self._classic_messages(symbols_tuple))),
            asyncio.create_task(pump(self._uta_liquidation_messages(symbols_tuple))),
        ]
        try:
            while True:
                yield await queue.get()
                queue.task_done()
        finally:
            for task in tasks:
                task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)


__all__ = [
    "BitgetMarketState",
    "BitgetPublicClient",
    "PUBLIC_UTA_WS_URL",
    "PUBLIC_WS_URL",
    "REST_BASE_URL",
    "parse_bitget_instruments",
]
