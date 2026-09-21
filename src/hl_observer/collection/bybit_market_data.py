"""Native public Bybit V5 market-data adapter (read-only).

Only public market endpoints are used.  The adapter keeps an in-memory L2 book,
merges derivative ticker metrics, and emits canonical NativeMarketSnapshot rows.
It never authenticates and never calls order/trade endpoints.
"""

from __future__ import annotations

import asyncio
import json
import time
import uuid
from dataclasses import dataclass, field
from typing import AsyncIterator, Iterable

import httpx
import websockets

from hl_observer.collection.backoff import compute_backoff_delay
from hl_observer.collection.feed_integrity import FeedIntegrityState, estimate_clock_sync
from hl_observer.collection.native_venue_market import (
    DESYNC,
    EXPLOITABLE,
    MarketLevel,
    NativeMarketSnapshot,
    UNMEASURABLE,
    canonical_coin,
)

SCHEMA_VERSION = "alina.bybit_market_data.v1"
REST_BASE_URL = "https://api.bybit.com"
PUBLIC_LINEAR_WS_URL = "wss://stream.bybit.com/v5/public/linear"


def _float(value: object) -> float | None:
    try:
        return float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None


def _int(value: object) -> int | None:
    try:
        return int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None


def _transport(payload: dict[str, object]) -> dict[str, object]:
    value = payload.get("_alina_transport")
    return value if isinstance(value, dict) else {}


def _levels(raw: Iterable[Iterable[object]], *, reverse: bool) -> list[MarketLevel]:
    rows: list[MarketLevel] = []
    for row in raw:
        values = list(row)
        if len(values) < 2:
            continue
        price, size = _float(values[0]), _float(values[1])
        if price is not None and size is not None and price > 0 and size > 0:
            rows.append(MarketLevel(price=price, size=size))
    rows.sort(key=lambda level: level.price, reverse=reverse)
    return rows


def parse_bybit_linear_instruments(payload: dict[str, object]) -> list[tuple[str, str]]:
    """Return ``[(coin, exchange_symbol)]`` for live USDT perpetuals."""
    result = payload.get("result")
    if not isinstance(result, dict):
        return []
    instruments = result.get("list")
    if not isinstance(instruments, list):
        return []
    rows: list[tuple[str, str]] = []
    for item in instruments:
        if not isinstance(item, dict):
            continue
        symbol = str(item.get("symbol") or "").upper()
        base = str(item.get("baseCoin") or canonical_coin(symbol)).upper()
        quote = str(item.get("quoteCoin") or "").upper()
        settle = str(item.get("settleCoin") or "").upper()
        status = str(item.get("status") or "Trading")
        contract_type = str(item.get("contractType") or "").lower()
        if not symbol or not base:
            continue
        if quote and quote != "USDT":
            continue
        if settle and settle != "USDT":
            continue
        if status not in {"Trading", "PendingOpen"}:
            continue
        if contract_type and "perpetual" not in contract_type:
            continue
        rows.append((base, symbol))
    return sorted(set(rows))


@dataclass(slots=True)
class BybitMarketState:
    symbol: str
    stale_after_ms: int = 1_000
    bids: dict[float, float] = field(default_factory=dict)
    asks: dict[float, float] = field(default_factory=dict)
    has_snapshot: bool = False
    update_id: int | None = None
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
    funding_interval_hours: float | None = None
    receive_mono_ns: int | None = None
    connection_id: str | None = None
    transport_rtt_ms: float | None = None
    clock_offset_ms: float | None = None
    integrity: FeedIntegrityState = field(default_factory=FeedIntegrityState)

    def apply_orderbook(self, payload: dict[str, object], *, receive_ts_ms: int | None = None) -> str:
        data = payload.get("data")
        if not isinstance(data, dict):
            return self._desync("INVALID_ORDERBOOK_PAYLOAD")
        kind = str(payload.get("type") or "")
        message_symbol = str(data.get("s") or self.symbol).upper()
        if message_symbol != self.symbol.upper():
            return self._desync("SYMBOL_MISMATCH")

        meta = _transport(payload)
        received = receive_ts_ms or _int(meta.get("receive_wall_ts_ms")) or int(time.time() * 1000)
        receive_mono = _int(meta.get("receive_mono_ns"))
        connection_id = str(meta.get("connection_id") or "") or None
        connection_changed = bool(
            connection_id and self.connection_id and connection_id != self.connection_id
        )
        if connection_changed:
            self.has_snapshot = False
            self.bids.clear()
            self.asks.clear()
        rtt = _float(meta.get("transport_rtt_ms"))
        clock_offset = _float(meta.get("clock_offset_ms"))
        update_id = _int(data.get("u"))
        sequence = _int(data.get("seq"))
        exchange_ts = _int(payload.get("cts")) or _int(data.get("cts")) or _int(payload.get("ts"))
        had_snapshot = self.has_snapshot

        if kind == "snapshot":
            self.bids.clear()
            self.asks.clear()
            self._apply_side(self.bids, data.get("b"))
            self._apply_side(self.asks, data.get("a"))
            self.has_snapshot = True
            ok, reasons = self.integrity.observe(
                sequence=update_id,
                exchange_ts_ms=exchange_ts,
                receive_ts_ms=received,
                receive_mono_ns=receive_mono,
                reset=had_snapshot or connection_changed,
            )
        elif kind == "delta":
            if not self.has_snapshot:
                return self._desync("DELTA_BEFORE_SNAPSHOT")
            if update_id == 1:
                self.has_snapshot = False
                self.bids.clear()
                self.asks.clear()
                self.integrity.observe(
                    sequence=update_id,
                    exchange_ts_ms=exchange_ts,
                    receive_ts_ms=received,
                    receive_mono_ns=receive_mono,
                    reset=True,
                )
                return self._desync("BYBIT_SERVICE_RESTART")
            ok, reasons = self.integrity.observe(
                sequence=update_id,
                exchange_ts_ms=exchange_ts,
                receive_ts_ms=received,
                receive_mono_ns=receive_mono,
            )
            if "DUPLICATE_SEQUENCE" in reasons:
                self.receive_ts_ms = received
                self.receive_mono_ns = receive_mono
                return self.quality
            if not ok:
                return self._desync(reasons[0] if reasons else "FEED_INTEGRITY")
            self._apply_side(self.bids, data.get("b"))
            self._apply_side(self.asks, data.get("a"))
        else:
            return self._desync("UNKNOWN_ORDERBOOK_TYPE")

        if not ok:
            return self._desync(reasons[0] if reasons else "FEED_INTEGRITY")
        self.update_id = update_id if update_id is not None else self.update_id
        self.sequence = sequence if sequence is not None else self.sequence
        self.exchange_ts_ms = exchange_ts or self.exchange_ts_ms
        self.receive_ts_ms = received
        self.receive_mono_ns = receive_mono
        self.connection_id = connection_id or self.connection_id
        self.transport_rtt_ms = rtt if rtt is not None else self.transport_rtt_ms
        self.clock_offset_ms = clock_offset if clock_offset is not None else self.clock_offset_ms
        self.quality = EXPLOITABLE if self._valid_bbo() else UNMEASURABLE
        self.reason = "" if self.quality == EXPLOITABLE else "INVALID_BBO"
        return self.quality

    def apply_ticker(self, payload: dict[str, object], *, receive_ts_ms: int | None = None) -> str:
        raw_data = payload.get("data")
        item: dict[str, object] | None = None
        if isinstance(raw_data, list) and raw_data and isinstance(raw_data[0], dict):
            item = raw_data[0]
        elif isinstance(raw_data, dict):
            item = raw_data
        if item is None:
            return self.quality
        symbol = str(item.get("symbol") or self.symbol).upper()
        if symbol != self.symbol.upper():
            return self._desync("SYMBOL_MISMATCH")
        meta = _transport(payload)
        self.last = _coalesce_float(item.get("lastPrice"), self.last)
        self.mark = _coalesce_float(item.get("markPrice"), self.mark)
        self.index = _coalesce_float(item.get("indexPrice"), self.index)
        self.volume_24h = _coalesce_float(item.get("volume24h"), self.volume_24h)
        self.open_interest = _coalesce_float(item.get("openInterest"), self.open_interest)
        self.funding_rate = _coalesce_float(item.get("fundingRate"), self.funding_rate)
        self.funding_interval_hours = _coalesce_float(item.get("fundingIntervalHour"), self.funding_interval_hours)
        self.exchange_ts_ms = _int(payload.get("ts")) or self.exchange_ts_ms
        self.receive_ts_ms = receive_ts_ms or _int(meta.get("receive_wall_ts_ms")) or self.receive_ts_ms or int(time.time() * 1000)
        self.receive_mono_ns = _int(meta.get("receive_mono_ns")) or self.receive_mono_ns
        self.connection_id = str(meta.get("connection_id") or "") or self.connection_id
        parsed_rtt = _float(meta.get("transport_rtt_ms"))
        if parsed_rtt is not None:
            self.transport_rtt_ms = parsed_rtt
        parsed_offset = _float(meta.get("clock_offset_ms"))
        if parsed_offset is not None:
            self.clock_offset_ms = parsed_offset
        return self.quality

    def snapshot(self, *, now_ms: int | None = None, depth: int = 200) -> NativeMarketSnapshot:
        bids = _levels(((p, s) for p, s in self.bids.items()), reverse=True)[:depth]
        asks = _levels(((p, s) for p, s in self.asks.items()), reverse=False)[:depth]
        bid = bids[0].price if bids else 0.0
        ask = asks[0].price if asks else 0.0
        return NativeMarketSnapshot.build(
            venue="bybit",
            coin=canonical_coin(self.symbol),
            exchange_symbol=self.symbol,
            bid=bid,
            ask=ask,
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
            volume_24h=self.volume_24h,
            open_interest=self.open_interest,
            funding_rate=self.funding_rate,
            funding_interval_hours=self.funding_interval_hours,
            sequence=self.sequence,
            update_id=self.update_id,
            connection_id=self.connection_id,
            receive_mono_ns=self.receive_mono_ns,
            transport_rtt_ms=self.transport_rtt_ms,
            clock_offset_ms=self.clock_offset_ms,
            gap_count=self.integrity.gaps,
            duplicate_count=self.integrity.duplicates,
            regression_count=(
                self.integrity.regressions
                + self.integrity.exchange_time_regressions
                + self.integrity.receive_time_regressions
                + self.integrity.monotonic_regressions
            ),
            reason=self.reason,
        )

    def _apply_side(self, side: dict[float, float], raw: object) -> None:
        if not isinstance(raw, list):
            return
        for row in raw:
            if not isinstance(row, (list, tuple)) or len(row) < 2:
                continue
            price, size = _float(row[0]), _float(row[1])
            if price is None or size is None or price <= 0:
                continue
            if size <= 0:
                side.pop(price, None)
            else:
                side[price] = size

    def _valid_bbo(self) -> bool:
        return bool(self.bids and self.asks and max(self.bids) <= min(self.asks))

    def _desync(self, reason: str) -> str:
        self.quality = DESYNC
        self.reason = reason
        return DESYNC


def _coalesce_float(value: object, current: float | None) -> float | None:
    parsed = _float(value)
    return current if parsed is None else parsed


class BybitPublicClient:
    """Small native public REST/WS client suitable for collectors and discovery."""

    def __init__(
        self,
        *,
        rest_base_url: str = REST_BASE_URL,
        ws_url: str = PUBLIC_LINEAR_WS_URL,
        orderbook_depth: int = 200,
    ) -> None:
        self.rest_base_url = rest_base_url.rstrip("/")
        self.ws_url = ws_url
        depth = int(orderbook_depth)
        if depth not in {1, 50, 200, 1000}:
            raise ValueError("Bybit orderbook_depth must be one of 1, 50, 200, 1000")
        self.orderbook_depth = depth

    def discover_usdt_perpetuals(self, *, timeout_s: float = 10.0) -> list[tuple[str, str]]:
        rows: list[tuple[str, str]] = []
        cursor = ""
        with httpx.Client(timeout=timeout_s) as client:
            while True:
                params: dict[str, object] = {"category": "linear", "limit": 1000}
                if cursor:
                    params["cursor"] = cursor
                response = client.get(f"{self.rest_base_url}/v5/market/instruments-info", params=params)
                response.raise_for_status()
                payload = response.json()
                if int(payload.get("retCode", -1)) != 0:
                    raise RuntimeError(f"Bybit instruments error: {payload.get('retMsg', 'unknown')}")
                rows.extend(parse_bybit_linear_instruments(payload))
                result = payload.get("result") or {}
                cursor = str(result.get("nextPageCursor") or "") if isinstance(result, dict) else ""
                if not cursor:
                    break
        return sorted(set(rows))

    def server_time_ms(self, *, timeout_s: float = 5.0) -> int:
        with httpx.Client(timeout=timeout_s) as client:
            response = client.get(f"{self.rest_base_url}/v5/market/time")
            response.raise_for_status()
            payload = response.json()
        if int(payload.get("retCode", -1)) != 0:
            raise RuntimeError(f"Bybit time error: {payload.get('retMsg', 'unknown')}")
        result = payload.get("result")
        if isinstance(result, dict):
            nano = _int(result.get("timeNano"))
            if nano is not None:
                return nano // 1_000_000
            seconds = _int(result.get("timeSecond"))
            if seconds is not None:
                return seconds * 1_000
        server = _int(payload.get("time"))
        if server is None:
            raise RuntimeError("Bybit server time missing")
        return server

    def measure_clock_sync(self, *, timeout_s: float = 5.0):
        sent = int(time.time() * 1_000)
        server = self.server_time_ms(timeout_s=timeout_s)
        received = int(time.time() * 1_000)
        return estimate_clock_sync(
            venue="bybit",
            server_ts_ms=server,
            send_wall_ts_ms=sent,
            receive_wall_ts_ms=received,
        )

    async def messages(self, symbols: Iterable[str]) -> AsyncIterator[dict[str, object]]:
        symbols = tuple(sorted({str(symbol).upper() for symbol in symbols if str(symbol).strip()}))
        if not symbols:
            return
        args = [
            topic
            for symbol in symbols
            for topic in (f"orderbook.{self.orderbook_depth}.{symbol}", f"tickers.{symbol}")
        ]
        attempt = 0
        while True:
            try:
                connection_id = f"bybit-{uuid.uuid4().hex}"
                async with websockets.connect(self.ws_url, ping_interval=20, ping_timeout=10) as socket:
                    await socket.send(json.dumps({"op": "subscribe", "args": args}))
                    attempt = 0
                    async for raw in socket:
                        receive_mono_ns = time.monotonic_ns()
                        receive_wall_ts_ms = int(time.time() * 1_000)
                        payload = json.loads(raw)
                        if isinstance(payload, dict):
                            latency = getattr(socket, "latency", None)
                            payload["_alina_transport"] = {
                                "connection_id": connection_id,
                                "receive_wall_ts_ms": receive_wall_ts_ms,
                                "receive_mono_ns": receive_mono_ns,
                                "transport_rtt_ms": (float(latency) * 1_000.0 if isinstance(latency, (int, float)) else None),
                            }
                            yield payload
            except asyncio.CancelledError:
                raise
            except Exception:
                delay = compute_backoff_delay(attempt=attempt, shard_key="bybit-public-ws")
                attempt += 1
                await asyncio.sleep(delay.delay_seconds)


__all__ = [
    "BybitMarketState",
    "BybitPublicClient",
    "PUBLIC_LINEAR_WS_URL",
    "REST_BASE_URL",
    "SCHEMA_VERSION",
    "parse_bybit_linear_instruments",
]
