"""Native public Bybit V5 market-data adapter (read-only).

Only public market endpoints are used.  The adapter keeps an in-memory L2 book,
merges derivative ticker metrics, and emits canonical NativeMarketSnapshot rows.
It never authenticates and never calls order/trade endpoints.
"""

from __future__ import annotations

import asyncio
import json
import time
from dataclasses import dataclass, field
from typing import AsyncIterator, Iterable

import httpx
import websockets

from hl_observer.collection.backoff import compute_backoff_delay
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

    def apply_orderbook(self, payload: dict[str, object], *, receive_ts_ms: int | None = None) -> str:
        data = payload.get("data")
        if not isinstance(data, dict):
            return self._desync("INVALID_ORDERBOOK_PAYLOAD")
        kind = str(payload.get("type") or "")
        message_symbol = str(data.get("s") or self.symbol).upper()
        if message_symbol != self.symbol.upper():
            return self._desync("SYMBOL_MISMATCH")
        update_id = _int(data.get("u"))
        sequence = _int(data.get("seq"))
        if kind == "snapshot":
            self.bids.clear()
            self.asks.clear()
            self._apply_side(self.bids, data.get("b"))
            self._apply_side(self.asks, data.get("a"))
            self.has_snapshot = True
        elif kind == "delta":
            if not self.has_snapshot:
                return self._desync("DELTA_BEFORE_SNAPSHOT")
            if update_id == 1:
                self.has_snapshot = False
                self.bids.clear()
                self.asks.clear()
                return self._desync("BYBIT_SERVICE_RESTART")
            if self.update_id is not None and update_id is not None and update_id < self.update_id:
                return self._desync("UPDATE_ID_REGRESSION")
            if self.sequence is not None and sequence is not None and sequence < self.sequence:
                return self._desync("SEQUENCE_REGRESSION")
            self._apply_side(self.bids, data.get("b"))
            self._apply_side(self.asks, data.get("a"))
        else:
            return self._desync("UNKNOWN_ORDERBOOK_TYPE")

        self.update_id = update_id if update_id is not None else self.update_id
        self.sequence = sequence if sequence is not None else self.sequence
        self.exchange_ts_ms = _int(payload.get("ts")) or self.exchange_ts_ms
        self.receive_ts_ms = receive_ts_ms or int(time.time() * 1000)
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
        self.last = _coalesce_float(item.get("lastPrice"), self.last)
        self.mark = _coalesce_float(item.get("markPrice"), self.mark)
        self.index = _coalesce_float(item.get("indexPrice"), self.index)
        self.volume_24h = _coalesce_float(item.get("volume24h"), self.volume_24h)
        self.open_interest = _coalesce_float(item.get("openInterest"), self.open_interest)
        self.funding_rate = _coalesce_float(item.get("fundingRate"), self.funding_rate)
        self.funding_interval_hours = _coalesce_float(
            item.get("fundingIntervalHour"), self.funding_interval_hours
        )
        self.exchange_ts_ms = _int(payload.get("ts")) or self.exchange_ts_ms
        self.receive_ts_ms = receive_ts_ms or self.receive_ts_ms or int(time.time() * 1000)
        return self.quality

    def snapshot(self, *, now_ms: int | None = None, depth: int = 50) -> NativeMarketSnapshot:
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

    def __init__(self, *, rest_base_url: str = REST_BASE_URL, ws_url: str = PUBLIC_LINEAR_WS_URL) -> None:
        self.rest_base_url = rest_base_url.rstrip("/")
        self.ws_url = ws_url

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

    async def messages(self, symbols: Iterable[str]) -> AsyncIterator[dict[str, object]]:
        symbols = tuple(sorted({str(symbol).upper() for symbol in symbols if str(symbol).strip()}))
        if not symbols:
            return
        args = [topic for symbol in symbols for topic in (f"orderbook.50.{symbol}", f"tickers.{symbol}")]
        attempt = 0
        while True:
            try:
                async with websockets.connect(self.ws_url, ping_interval=20, ping_timeout=10) as socket:
                    await socket.send(json.dumps({"op": "subscribe", "args": args}))
                    attempt = 0
                    async for raw in socket:
                        payload = json.loads(raw)
                        if isinstance(payload, dict):
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
