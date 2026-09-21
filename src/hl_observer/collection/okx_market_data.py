"""Native public OKX V5 market-data adapter (read-only).

Uses only public instruments/order-book/ticker/funding/open-interest data.  The
baseline depth feed is ``books5`` because it is public and requires no VIP/auth.
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

SCHEMA_VERSION = "alina.okx_market_data.v1"
REST_BASE_URL = "https://www.okx.com"
PUBLIC_WS_URL = "wss://ws.okx.com:8443/ws/v5/public"


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


def parse_okx_swap_instruments(payload: dict[str, object]) -> list[tuple[str, str]]:
    """Return ``[(coin, instId)]`` for live USDT perpetual swaps."""
    data = payload.get("data")
    if not isinstance(data, list):
        return []
    rows: list[tuple[str, str]] = []
    for item in data:
        if not isinstance(item, dict):
            continue
        inst_id = str(item.get("instId") or "").upper()
        inst_type = str(item.get("instType") or "SWAP").upper()
        settle = str(item.get("settleCcy") or "").upper()
        state = str(item.get("state") or "live").lower()
        if inst_type != "SWAP" or state != "live" or not inst_id.endswith("-USDT-SWAP"):
            continue
        if settle and settle != "USDT":
            continue
        coin = str(item.get("ctValCcy") or canonical_coin(inst_id)).upper()
        if coin:
            rows.append((coin, inst_id))
    return sorted(set(rows))


def _parse_levels(raw: object, *, reverse: bool) -> list[MarketLevel]:
    if not isinstance(raw, list):
        return []
    levels: list[MarketLevel] = []
    for row in raw:
        if not isinstance(row, (list, tuple)) or len(row) < 2:
            continue
        price, size = _float(row[0]), _float(row[1])
        if price is not None and size is not None and price > 0 and size > 0:
            levels.append(MarketLevel(price=price, size=size))
    levels.sort(key=lambda item: item.price, reverse=reverse)
    return levels


@dataclass(slots=True)
class OkxMarketState:
    inst_id: str
    stale_after_ms: int = 1_000
    bids: tuple[MarketLevel, ...] = ()
    asks: tuple[MarketLevel, ...] = ()
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

    def apply(self, payload: dict[str, object], *, receive_ts_ms: int | None = None) -> str:
        arg = payload.get("arg")
        channel = str(arg.get("channel") or "") if isinstance(arg, dict) else ""
        data = payload.get("data")
        if not isinstance(data, list) or not data or not isinstance(data[0], dict):
            return self.quality
        item = data[0]
        inst = str(item.get("instId") or (arg.get("instId") if isinstance(arg, dict) else "") or self.inst_id).upper()
        if inst != self.inst_id.upper():
            return self._desync("SYMBOL_MISMATCH")
        meta = _transport(payload)
        received = receive_ts_ms or _int(meta.get("receive_wall_ts_ms")) or int(time.time() * 1000)
        self.receive_mono_ns = _int(meta.get("receive_mono_ns")) or self.receive_mono_ns
        self.connection_id = str(meta.get("connection_id") or "") or self.connection_id
        parsed_rtt = _float(meta.get("transport_rtt_ms"))
        if parsed_rtt is not None:
            self.transport_rtt_ms = parsed_rtt
        parsed_offset = _float(meta.get("clock_offset_ms"))
        if parsed_offset is not None:
            self.clock_offset_ms = parsed_offset

        if channel in {"books5", "bbo-tbt", "books"}:
            return self._apply_book(item, receive_ts_ms=received, receive_mono_ns=self.receive_mono_ns)
        if channel == "tickers":
            self.last = _coalesce(item.get("last"), self.last)
            self.volume_24h = _coalesce(item.get("vol24h"), self.volume_24h)
            self.exchange_ts_ms = _int(item.get("ts")) or self.exchange_ts_ms
        elif channel == "funding-rate":
            self.funding_rate = _coalesce(item.get("fundingRate"), self.funding_rate)
            self.exchange_ts_ms = _int(item.get("ts")) or self.exchange_ts_ms
            interval_ms = _funding_interval_ms(item)
            if interval_ms:
                self.funding_interval_hours = interval_ms / 3_600_000.0
        elif channel == "open-interest":
            self.open_interest = _coalesce(item.get("oi"), self.open_interest)
            self.exchange_ts_ms = _int(item.get("ts")) or self.exchange_ts_ms
        elif channel == "mark-price":
            self.mark = _coalesce(item.get("markPx"), self.mark)
            self.exchange_ts_ms = _int(item.get("ts")) or self.exchange_ts_ms
        elif channel == "index-tickers":
            self.index = _coalesce(item.get("idxPx"), self.index)
            self.exchange_ts_ms = _int(item.get("ts")) or self.exchange_ts_ms
        self.receive_ts_ms = received
        return self.quality

    def _apply_book(self, item: dict[str, object], *, receive_ts_ms: int, receive_mono_ns: int | None = None) -> str:
        seq = _int(item.get("seqId"))
        prev = _int(item.get("prevSeqId"))
        exchange_ts = _int(item.get("ts"))
        ok, reasons = self.integrity.observe(
            sequence=seq,
            prev_sequence=prev,
            exchange_ts_ms=exchange_ts,
            receive_ts_ms=receive_ts_ms,
            receive_mono_ns=receive_mono_ns,
        )
        if "DUPLICATE_SEQUENCE" in reasons:
            self.receive_ts_ms = receive_ts_ms
            return self.quality
        if not ok:
            return self._desync(reasons[0] if reasons else "FEED_INTEGRITY")

        bids = _parse_levels(item.get("bids"), reverse=True)
        asks = _parse_levels(item.get("asks"), reverse=False)
        # books5 and bbo-tbt are full snapshots for their advertised depth.
        # Incremental books need a dedicated reconstruction path.
        if bids:
            self.bids = tuple(bids)
        if asks:
            self.asks = tuple(asks)
        self.sequence = seq if seq is not None else self.sequence
        self.exchange_ts_ms = exchange_ts or self.exchange_ts_ms
        self.receive_ts_ms = receive_ts_ms
        if self._valid_bbo():
            self.quality = EXPLOITABLE
            self.reason = ""
        else:
            self.quality = UNMEASURABLE
            self.reason = "INVALID_BBO"
        return self.quality

    def snapshot(self, *, now_ms: int | None = None) -> NativeMarketSnapshot:
        bid = self.bids[0].price if self.bids else 0.0
        ask = self.asks[0].price if self.asks else 0.0
        return NativeMarketSnapshot.build(
            venue="okx",
            coin=canonical_coin(self.inst_id),
            exchange_symbol=self.inst_id,
            bid=bid,
            ask=ask,
            bids=self.bids,
            asks=self.asks,
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

    def _valid_bbo(self) -> bool:
        return bool(self.bids and self.asks and self.bids[0].price <= self.asks[0].price)

    def _desync(self, reason: str) -> str:
        self.quality = DESYNC
        self.reason = reason
        return DESYNC


def _coalesce(value: object, current: float | None) -> float | None:
    parsed = _float(value)
    return current if parsed is None else parsed


def _funding_interval_ms(item: dict[str, object]) -> int | None:
    current = _int(item.get("fundingTime"))
    nxt = _int(item.get("nextFundingTime"))
    if current is not None and nxt is not None and nxt > current:
        return nxt - current
    return None


class OkxPublicClient:
    """Native public REST/WS client; no auth and no order endpoints."""

    def __init__(self, *, rest_base_url: str = REST_BASE_URL, ws_url: str = PUBLIC_WS_URL) -> None:
        self.rest_base_url = rest_base_url.rstrip("/")
        self.ws_url = ws_url

    def discover_usdt_perpetuals(self, *, timeout_s: float = 10.0) -> list[tuple[str, str]]:
        with httpx.Client(timeout=timeout_s) as client:
            response = client.get(
                f"{self.rest_base_url}/api/v5/public/instruments", params={"instType": "SWAP"}
            )
            response.raise_for_status()
            payload = response.json()
        if str(payload.get("code", "0")) != "0":
            raise RuntimeError(f"OKX instruments error: {payload.get('msg', 'unknown')}")
        return parse_okx_swap_instruments(payload)

    def server_time_ms(self, *, timeout_s: float = 5.0) -> int:
        with httpx.Client(timeout=timeout_s) as client:
            response = client.get(f"{self.rest_base_url}/api/v5/public/time")
            response.raise_for_status()
            payload = response.json()
        data = payload.get("data")
        if str(payload.get("code", "0")) != "0" or not isinstance(data, list) or not data:
            raise RuntimeError(f"OKX time error: {payload.get('msg', 'unknown')}")
        server = _int(data[0].get("ts")) if isinstance(data[0], dict) else None
        if server is None:
            raise RuntimeError("OKX server time missing")
        return server

    def measure_clock_sync(self, *, timeout_s: float = 5.0):
        sent = int(time.time() * 1_000)
        server = self.server_time_ms(timeout_s=timeout_s)
        received = int(time.time() * 1_000)
        return estimate_clock_sync(
            venue="okx",
            server_ts_ms=server,
            send_wall_ts_ms=sent,
            receive_wall_ts_ms=received,
        )

    async def messages(self, inst_ids: Iterable[str]) -> AsyncIterator[dict[str, object]]:
        inst_ids = tuple(sorted({str(value).upper() for value in inst_ids if str(value).strip()}))
        if not inst_ids:
            return
        args = [
            {"channel": channel, "instId": inst_id}
            for inst_id in inst_ids
            for channel in ("books5", "tickers", "funding-rate", "open-interest", "mark-price")
        ]
        attempt = 0
        while True:
            try:
                connection_id = f"okx-{uuid.uuid4().hex}"
                async with websockets.connect(self.ws_url, ping_interval=20, ping_timeout=10) as socket:
                    await socket.send(json.dumps({"op": "subscribe", "args": args}))
                    attempt = 0
                    async for raw in socket:
                        receive_mono_ns = time.monotonic_ns()
                        receive_wall_ts_ms = int(time.time() * 1_000)
                        if raw == "pong":
                            continue
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
                delay = compute_backoff_delay(attempt=attempt, shard_key="okx-public-ws")
                attempt += 1
                await asyncio.sleep(delay.delay_seconds)


__all__ = [
    "OkxMarketState",
    "OkxPublicClient",
    "PUBLIC_WS_URL",
    "REST_BASE_URL",
    "SCHEMA_VERSION",
    "parse_okx_swap_instruments",
]
