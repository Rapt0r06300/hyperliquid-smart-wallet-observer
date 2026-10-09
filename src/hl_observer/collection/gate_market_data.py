"""Gate.io USDT perpetual public collector (read-only)."""
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
from hl_observer.collection.tick_dataset import TickEnvelope
from hl_observer.realtime.feed_quality import FeedEventKind

REST_BASE_URL = "https://api.gateio.ws/api/v4"
PUBLIC_WS_URL = "wss://fx-ws.gateio.ws/v4/ws/usdt"
VWAP_TARGET_QUOTE_NOTIONALS_USD = (10, 25, 50, 100, 250, 500, 1000)


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


def _epoch_ms(v: Any) -> int | None:
    try:
        value = float(v)
    except (TypeError, ValueError):
        return None
    if value <= 0:
        return None
    if value < 10_000_000_000:
        value *= 1000.0
    return int(value)


def parse_gate_contracts(payload: Any) -> list[tuple[str, str]]:
    rows = payload.get("data", payload) if isinstance(payload, dict) else payload
    out = []
    for item in rows or []:
        if not isinstance(item, dict):
            continue
        symbol = str(item.get("name") or item.get("contract") or "").upper()
        if not symbol or item.get("in_delisting") in (True, "true"):
            continue
        if str(item.get("type") or "direct").lower() not in {"direct", ""}:
            continue
        out.append((canonical_coin(symbol), symbol))
    return sorted({x for x in out if x[0]})


@dataclass(slots=True)
class GateMarketState:
    contract: str
    stale_after_ms: int = 1_000
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

    def apply_book(self, payload: dict[str, Any], *, receive_ts_ms: int | None = None) -> str:
        meta = payload.get("_alina_transport")
        transport = dict(meta) if isinstance(meta, Mapping) else {}
        first = _i(payload.get("U") or payload.get("first_update_id"))
        last = _i(payload.get("u") or payload.get("last_update_id") or payload.get("id"))
        # Gate sends an explicit 'full' marker when a payload is a complete
        # authoritative book snapshot. Replace the book and re-anchor its
        # sequence rather than comparing against a prior incremental epoch.
        # Historical gap counters are retained as evidence.
        if payload.get("full") is True:
            bids = payload.get("b") or payload.get("bids")
            asks = payload.get("a") or payload.get("asks")
            if not isinstance(bids, list) or not bids or not isinstance(asks, list) or not asks:
                self.quality, self.reason = UNMEASURABLE, "INCOMPLETE_FULL_SNAPSHOT"
                return self.quality
            self.bids.clear()
            self.asks.clear()
            self.sequence = None
        if self.sequence is not None and last is not None:
            if first is not None and first > self.sequence + 1:
                self.gap_count += 1
                self.quality, self.reason = DESYNC, "SEQUENCE_GAP"
                return self.quality
            if last < self.sequence:
                self.regression_count += 1
                self.quality, self.reason = DESYNC, "SEQUENCE_REGRESSION"
                return self.quality
        for side, target in (
            (payload.get("b") or payload.get("bids"), self.bids),
            (payload.get("a") or payload.get("asks"), self.asks),
        ):
            for row in side or []:
                if isinstance(row, (list, tuple)) and len(row) >= 2:
                    price, size = _f(row[0]), _f(row[1])
                elif isinstance(row, dict):
                    price, size = _f(row.get("p") or row.get("price")), _f(row.get("s") or row.get("size"))
                else:
                    continue
                if price is None or price <= 0 or size is None:
                    continue
                if size <= 0:
                    target.pop(price, None)
                else:
                    target[price] = size
        self.sequence = last if last is not None else self.sequence
        self.exchange_ts_ms = _epoch_ms(payload.get("time_ms") or payload.get("t") or payload.get("time")) or self.exchange_ts_ms
        self.receive_ts_ms = receive_ts_ms or _i(transport.get("receive_wall_ts_ms")) or int(time.time() * 1000)
        self.receive_mono_ns = _i(transport.get("receive_mono_ns")) or self.receive_mono_ns
        self.connection_id = str(transport.get("connection_id") or "") or self.connection_id
        if transport.get("transport_rtt_ms") is not None:
            self.transport_rtt_ms = _f(transport.get("transport_rtt_ms"))
        if transport.get("clock_offset_ms") is not None:
            self.clock_offset_ms = _f(transport.get("clock_offset_ms"))
        self.quality = EXPLOITABLE if self._valid() else UNMEASURABLE
        self.reason = "" if self.quality == EXPLOITABLE else "INVALID_BBO"
        return self.quality

    def apply_ticker(self, payload: dict[str, Any]) -> str:
        self.last = _f(payload.get("last") or payload.get("last_price")) or self.last
        self.mark = _f(payload.get("mark_price") or payload.get("mark")) or self.mark
        self.index = _f(payload.get("index_price") or payload.get("index")) or self.index
        self.volume_24h = _f(payload.get("volume_24h_base") or payload.get("volume_24h")) or self.volume_24h
        self.open_interest = _f(payload.get("total_size") or payload.get("open_interest")) or self.open_interest
        if payload.get("funding_rate") is not None:
            self.funding_rate = _f(payload.get("funding_rate"))
        return self.quality

    def snapshot(self, *, now_ms: int | None = None, depth: int = 100) -> NativeMarketSnapshot:
        bids = tuple(MarketLevel(p, s) for p, s in sorted(self.bids.items(), reverse=True)[:depth])
        asks = tuple(MarketLevel(p, s) for p, s in sorted(self.asks.items())[:depth])
        return NativeMarketSnapshot.build(
            venue="gate",
            coin=canonical_coin(self.contract),
            exchange_symbol=self.contract,
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
            volume_24h=self.volume_24h,
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

    def _valid(self) -> bool:
        return bool(self.bids and self.asks and max(self.bids) <= min(self.asks))


class GatePublicClient:
    def __init__(
        self,
        *,
        rest_base_url: str = REST_BASE_URL,
        ws_url: str = PUBLIC_WS_URL,
        session_refresh_s: float = 900.0,
    ) -> None:
        self.rest_base_url = rest_base_url.rstrip("/")
        self.ws_url = ws_url
        self.session_refresh_s = max(60.0, float(session_refresh_s))
        self.capture_tier = CaptureTier.B
        self.capture_tiers_by_symbol: dict[str, CaptureTier] = {}
        self.last_instrument_metadata: list[dict[str, Any]] = []

    def set_capture_profile(self, tier: CaptureTier | str) -> None:
        self.capture_tier = capture_profile("gate", tier).tier

    def set_capture_profiles(self, tiers: Mapping[str, CaptureTier | str]) -> None:
        self.capture_tiers_by_symbol = {
            str(symbol).upper(): capture_profile("gate", tier).tier
            for symbol, tier in tiers.items()
        }

    def subscription_args(self, contracts: Iterable[str]) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        for contract in sorted({str(c).upper() for c in contracts if str(c).strip()}):
            profile = capture_profile(
                "gate", self.capture_tiers_by_symbol.get(contract, self.capture_tier)
            )
            for channel in profile.channels:
                payload = [contract]
                if channel == "futures.order_book_update":
                    payload += ["100ms", str(profile.depth)]
                rows.append({"channel": channel, "event": "subscribe", "payload": payload})
        return rows

    def discover_usdt_perpetuals(self, *, timeout_s: float = 10.0) -> list[tuple[str, str]]:
        with httpx.Client(timeout=timeout_s) as client:
            response = client.get(f"{self.rest_base_url}/futures/usdt/contracts")
            response.raise_for_status()
            payload = response.json()
        rows = payload.get("data", payload) if isinstance(payload, dict) else payload
        self.last_instrument_metadata = [dict(row) for row in (rows or []) if isinstance(row, dict)]
        return parse_gate_contracts(payload)

    def server_time_ms(self, *, timeout_s: float = 5.0) -> int:
        with httpx.Client(timeout=timeout_s) as client:
            response = client.get(f"{self.rest_base_url}/spot/time")
            response.raise_for_status()
            payload = response.json()
        server = _i(payload.get("server_time")) if isinstance(payload, Mapping) else None
        if server is None:
            raise RuntimeError("Gate server time missing")
        return server

    def measure_clock_sync(self, *, timeout_s: float = 5.0):
        sent = int(time.time() * 1000)
        server = self.server_time_ms(timeout_s=timeout_s)
        received = int(time.time() * 1000)
        return estimate_clock_sync(
            venue="gate",
            server_ts_ms=server,
            send_wall_ts_ms=sent,
            receive_wall_ts_ms=received,
        )

    def bootstrap_envelopes(
        self,
        contracts: Iterable[str],
        *,
        timeout_s: float = 10.0,
        depth: int = 100,
    ) -> list[TickEnvelope]:
        """Capture an official REST base book before applying incremental WS updates."""
        rows: list[TickEnvelope] = []
        with httpx.Client(timeout=timeout_s) as client:
            for contract in sorted({str(c).upper() for c in contracts if str(c).strip()}):
                sent = int(time.time() * 1000)
                response = client.get(
                    f"{self.rest_base_url}/futures/usdt/order_book",
                    params={
                        "contract": contract,
                        "limit": max(1, min(100, int(depth))),
                        "with_id": "true",
                    },
                )
                response.raise_for_status()
                payload = response.json()
                received = int(time.time() * 1000)
                mono = time.monotonic_ns()
                if not isinstance(payload, Mapping):
                    continue
                asks = payload.get("asks") if isinstance(payload.get("asks"), list) else []
                bids = payload.get("bids") if isinstance(payload.get("bids"), list) else []
                rows.append(
                    TickEnvelope(
                        source_id="gate_public_rest",
                        channel="l2Book",
                        instrument=contract,
                        event_kind=FeedEventKind.SNAPSHOT,
                        raw_payload=dict(payload),
                        exchange_ts_ms=_epoch_ms(payload.get("current")),
                        received_ts_ms=received,
                        local_monotonic_ns=mono,
                        connection_id=None,
                        sequence=_i(payload.get("id")),
                        provenance={
                            "url": f"{self.rest_base_url}/futures/usdt/order_book",
                            "network": "mainnet",
                            "access": "read_only",
                            "transport": "https",
                            "authenticated": False,
                            "request_send_wall_ms": sent,
                            "request_receive_wall_ms": received,
                            "snapshot_role": "official_base_for_incremental_depth",
                        },
                        parsed_summary={
                            "bid_levels": len(bids),
                            "ask_levels": len(asks),
                            "snapshot_id": _i(payload.get("id")),
                            "vwap_target_quote_notionals_usd": list(VWAP_TARGET_QUOTE_NOTIONALS_USD),
                            "depth_curve_replay_ready": bool(bids and asks),
                            "data_gate_ready": False,
                        },
                    )
                )
        return rows

    async def messages(self, contracts: Iterable[str]) -> AsyncIterator[dict[str, Any]]:
        contracts = tuple(sorted({str(c).upper() for c in contracts if str(c).strip()}))
        if not contracts:
            return
        subscriptions = self.subscription_args(contracts)
        attempt = 0
        while True:
            try:
                connection_id = f"gate-{uuid.uuid4().hex}"
                session_started = time.monotonic()
                async with websockets.connect(
                    self.ws_url,
                    ping_interval=20,
                    ping_timeout=10,
                    extra_headers={"X-Gate-Size-Decimal": "1"},
                ) as socket:
                    for message in subscriptions:
                        await socket.send(json.dumps(message))
                    attempt = 0
                    async for raw in socket:
                        receive_mono_ns = time.monotonic_ns()
                        receive_wall_ts_ms = int(time.time() * 1000)
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
                delay = compute_backoff_delay(attempt=attempt, shard_key="gate-public-ws")
                attempt += 1
                await asyncio.sleep(delay.delay_seconds)


__all__ = [
    "GateMarketState",
    "GatePublicClient",
    "PUBLIC_WS_URL",
    "REST_BASE_URL",
    "VWAP_TARGET_QUOTE_NOTIONALS_USD",
    "parse_gate_contracts",
]
