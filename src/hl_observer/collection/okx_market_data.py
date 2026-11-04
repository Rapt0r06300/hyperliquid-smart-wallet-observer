"""Native public OKX V5 market-data adapter (read-only).

Uses only public instruments/order-book/ticker/funding/open-interest data.  The
baseline depth feed is ``books5`` because it is public and requires no VIP/auth.
"""

from __future__ import annotations

import asyncio
import json
import math
import time
import uuid
from collections.abc import AsyncIterator, Iterable, Mapping
from dataclasses import dataclass, field
import zlib

import httpx
import websockets

from hl_observer.collection.backoff import compute_backoff_delay
from hl_observer.collection.coin_universe import validate_okx_linear_usdt_swap
from hl_observer.collection.feed_integrity import FeedIntegrityState, estimate_clock_sync
from hl_observer.collection.market_capture_tiers import CaptureTier, capture_profile
from hl_observer.collection.native_venue_market import (
    DESYNC,
    EXPLOITABLE,
    UNMEASURABLE,
    MarketLevel,
    NativeMarketSnapshot,
    canonical_coin,
)

SCHEMA_VERSION = "alina.okx_market_data.v1"
REST_BASE_URL = "https://www.okx.com"
PUBLIC_WS_URL = "wss://ws.okx.com/ws/v5/public"
BUSINESS_WS_URL = "wss://ws.okx.com:8443/ws/v5/business"


def _float(value: object) -> float | None:
    try:
        parsed = float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None
    return parsed if math.isfinite(parsed) else None


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
        eligible, _ = validate_okx_linear_usdt_swap(item)
        if not eligible:
            continue
        coin = str(item.get("ctValCcy") or canonical_coin(inst_id)).upper()
        if coin:
            rows.append((coin, inst_id))
    return sorted(set(rows))


def okx_book_checksum(bids: object, asks: object, *, depth: int = 25) -> int | None:
    """Return signed OKX CRC32 over alternating bid/ask tokens in venue order."""
    tokens: list[str] = []
    bid_rows = bids if isinstance(bids, list) else []
    ask_rows = asks if isinstance(asks, list) else []
    for index in range(max(0, int(depth))):
        if index < len(bid_rows):
            row = bid_rows[index]
            if isinstance(row, (list, tuple)) and len(row) >= 2:
                tokens.extend((str(row[0]), str(row[1])))
        if index < len(ask_rows):
            row = ask_rows[index]
            if isinstance(row, (list, tuple)) and len(row) >= 2:
                tokens.extend((str(row[0]), str(row[1])))
    if not tokens:
        return None
    unsigned = zlib.crc32(":".join(tokens).encode("utf-8"))
    return unsigned if unsigned < 2**31 else unsigned - 2**32


def _checksum_value(value: object) -> int | None:
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return None


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
    book_bids: dict[float, float] = field(default_factory=dict, repr=False)
    book_asks: dict[float, float] = field(default_factory=dict, repr=False)
    book_ready: bool = False
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
    book_channel: str | None = None
    book_source: str | None = None
    subscription_epoch: int | None = None
    awaiting_snapshot_reset: bool = False

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
        incoming_connection = str(meta.get("connection_id") or "") or None
        connection_reset = bool(
            incoming_connection
            and self.connection_id
            and incoming_connection != self.connection_id
        )
        self.receive_mono_ns = _int(meta.get("receive_mono_ns")) or self.receive_mono_ns
        self.connection_id = incoming_connection or self.connection_id
        parsed_rtt = _float(meta.get("transport_rtt_ms"))
        if parsed_rtt is not None:
            self.transport_rtt_ms = parsed_rtt
        parsed_offset = _float(meta.get("clock_offset_ms"))
        if parsed_offset is not None:
            self.clock_offset_ms = parsed_offset

        if channel in {"books5", "bbo-tbt", "books"}:
            return self._apply_book(
                item,
                channel=channel,
                action=str(payload.get("action") or "snapshot"),
                receive_ts_ms=received,
                receive_mono_ns=self.receive_mono_ns,
                connection_reset=connection_reset,
                subscription_epoch=_int(meta.get("subscription_epoch")),
                book_source=str(meta.get("book_source") or "ws").lower(),
            )
        if str(payload.get("event") or "").lower() in {"notice", "maintenance"}:
            return self.quality
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

    def _apply_book(
        self,
        item: dict[str, object],
        *,
        channel: str,
        action: str,
        receive_ts_ms: int,
        receive_mono_ns: int | None = None,
        connection_reset: bool = False,
        subscription_epoch: int | None = None,
        book_source: str = "ws",
    ) -> str:
        seq = _int(item.get("seqId"))
        prev = _int(item.get("prevSeqId"))
        exchange_ts = _int(item.get("ts"))
        incremental = channel == "books"
        is_snapshot = action == "snapshot" or not incremental

        if connection_reset:
            self._clear_book()
            self.book_channel = None
            self.book_source = None
            self.subscription_epoch = None

        if self.book_channel is not None and channel != self.book_channel:
            self._clear_book()
            return self._desync("CHANNEL_CHANGED")
        if self.book_source is not None and book_source != self.book_source:
            self._clear_book()
            return self._desync("BOOK_SOURCE_CHANGED")

        if (
            subscription_epoch is not None
            and self.subscription_epoch is not None
            and subscription_epoch < self.subscription_epoch
        ):
            self._clear_book()
            return self._desync("STALE_SUBSCRIPTION_SNAPSHOT")
        if (
            subscription_epoch is not None
            and self.subscription_epoch is not None
            and subscription_epoch > self.subscription_epoch
        ):
            if not is_snapshot:
                self._clear_book()
                return self._desync("SUBSCRIPTION_EPOCH_WITHOUT_SNAPSHOT")
            self._clear_book()
            self.awaiting_snapshot_reset = True
        self.book_channel = channel
        self.book_source = book_source
        if subscription_epoch is not None:
            self.subscription_epoch = subscription_epoch

        if seq is not None and prev is not None and seq == prev:
            self._clear_book()
            return self._desync("SEQUENCE_EQUALS_PREVIOUS")
        prev_discordant = (
            not connection_reset
            and self.sequence is not None
            and prev is not None
            and prev not in {self.sequence, -1}
        )

        if incremental and not is_snapshot and not self.book_ready:
            return self._desync("DELTA_BEFORE_SNAPSHOT")

        ok, reasons = self.integrity.observe(
            sequence=seq,
            prev_sequence=prev,
            exchange_ts_ms=exchange_ts,
            receive_ts_ms=receive_ts_ms,
            receive_mono_ns=receive_mono_ns,
            # A stream that was explicitly quarantined may re-anchor only on
            # its next snapshot; ordinary books5 snapshots still retain the
            # existing sequence-chain checks above.
            reset=connection_reset
            or (self.awaiting_snapshot_reset and is_snapshot)
            or (incremental and is_snapshot and self.book_ready),
        )
        if "DUPLICATE_SEQUENCE" in reasons and incremental and not is_snapshot:
            self.receive_ts_ms = receive_ts_ms
            return self.quality
        if "DUPLICATE_SEQUENCE" in reasons and not incremental:
            self._clear_book()
            return self._desync("DUPLICATE_SNAPSHOT_SEQUENCE")
        if not ok:
            self._clear_book()
            return self._desync(
                "PREV_SEQUENCE_DISCORDANT"
                if prev_discordant
                else (reasons[0] if reasons else "FEED_INTEGRITY")
            )

        if incremental:
            candidate_bids = {} if is_snapshot else dict(self.book_bids)
            candidate_asks = {} if is_snapshot else dict(self.book_asks)
            self._apply_delta_side(candidate_bids, item.get("bids"))
            self._apply_delta_side(candidate_asks, item.get("asks"))
            if not self._checksum_valid(
                item.get("checksum"),
                self._checksum_from_maps(candidate_bids, candidate_asks),
            ):
                self._clear_book()
                return self._desync("CHECKSUM_MISMATCH")
            if is_snapshot:
                self.book_bids.clear()
                self.book_asks.clear()
                self._apply_delta_side(self.book_bids, item.get("bids"))
                self._apply_delta_side(self.book_asks, item.get("asks"))
                self.book_ready = True
            else:
                self._apply_delta_side(self.book_bids, item.get("bids"))
                self._apply_delta_side(self.book_asks, item.get("asks"))
            self.bids = tuple(
                MarketLevel(price=price, size=size)
                for price, size in sorted(self.book_bids.items(), reverse=True)[:400]
            )
            self.asks = tuple(
                MarketLevel(price=price, size=size)
                for price, size in sorted(self.book_asks.items())[:400]
            )
        else:
            if not self._checksum_valid(
                item.get("checksum"),
                okx_book_checksum(item.get("bids"), item.get("asks")),
            ):
                self._clear_book()
                return self._desync("CHECKSUM_MISMATCH")
            self.bids = tuple(_parse_levels(item.get("bids"), reverse=True))
            self.asks = tuple(_parse_levels(item.get("asks"), reverse=False))
            self.book_ready = bool(self.bids and self.asks)

        self.sequence = seq if seq is not None else self.sequence
        self.awaiting_snapshot_reset = False
        self.exchange_ts_ms = exchange_ts or self.exchange_ts_ms
        self.receive_ts_ms = receive_ts_ms
        if self._valid_bbo():
            self.quality = EXPLOITABLE
            self.reason = ""
        else:
            self.quality = UNMEASURABLE
            self.reason = "INVALID_BBO"
        return self.quality

    @staticmethod
    def _apply_delta_side(side: dict[float, float], raw: object) -> None:
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

    @staticmethod
    def _checksum_from_maps(
        bids: dict[float, float], asks: dict[float, float]
    ) -> int | None:
        bid_rows = [
            [format(price, "g"), format(size, "g")]
            for price, size in sorted(bids.items(), reverse=True)[:25]
        ]
        ask_rows = [
            [format(price, "g"), format(size, "g")]
            for price, size in sorted(asks.items())[:25]
        ]
        return okx_book_checksum(bid_rows, ask_rows)

    @staticmethod
    def _checksum_valid(expected: object, actual: int | None) -> bool:
        if expected is None:
            return True
        parsed = _checksum_value(expected)
        return parsed is not None and actual is not None and parsed == actual

    def _clear_book(self) -> None:
        self.book_ready = False
        self.bids = ()
        self.asks = ()
        self.book_bids.clear()
        self.book_asks.clear()
        self.awaiting_snapshot_reset = True

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

    def __init__(
        self,
        *,
        rest_base_url: str = REST_BASE_URL,
        ws_url: str = PUBLIC_WS_URL,
        business_ws_url: str = BUSINESS_WS_URL,
        session_refresh_s: float = 900.0,
    ) -> None:
        self.rest_base_url = rest_base_url.rstrip("/")
        self.ws_url = ws_url
        self.business_ws_url = business_ws_url
        self.session_refresh_s = max(60.0, float(session_refresh_s))
        self.capture_tier = CaptureTier.B
        self.capture_tiers_by_symbol: dict[str, CaptureTier] = {}
        self.last_instrument_metadata: list[dict[str, object]] = []

    def set_capture_profile(self, tier: CaptureTier | str) -> None:
        self.capture_tier = capture_profile("okx", tier).tier

    def set_capture_profiles(self, tiers: Mapping[str, CaptureTier | str]) -> None:
        self.capture_tiers_by_symbol = {
            str(symbol).upper(): capture_profile("okx", tier).tier
            for symbol, tier in tiers.items()
        }

    def subscription_args(self, inst_ids: Iterable[str]) -> list[dict[str, str]]:
        return [
            {
                # The public ``trades`` channel aggregates maker matches. The
                # unauthenticated business ``trades-all`` channel emits one
                # native trade per row and is therefore exactly reconcilable.
                "channel": "trades-all" if channel == "trades" else channel,
                "instId": inst_id,
            }
            for inst_id in sorted({str(v).upper() for v in inst_ids if str(v).strip()})
            for channel in capture_profile(
                "okx", self.capture_tiers_by_symbol.get(inst_id, self.capture_tier)
            ).channels
        ]

    def subscription_groups(
        self, inst_ids: Iterable[str]
    ) -> tuple[list[dict[str, str]], list[dict[str, str]]]:
        """Split public and business subscriptions without duplicating trades."""
        public: list[dict[str, str]] = []
        business: list[dict[str, str]] = []
        for arg in self.subscription_args(inst_ids):
            (business if arg["channel"] == "trades-all" else public).append(arg)
        return public, business

    def subscription_batches(
        self,
        inst_ids: Iterable[str],
        *,
        max_args: int = 100,
    ) -> list[list[dict[str, str]]]:
        """Split deterministic subscriptions before a venue rate-limit boundary."""
        limit = max(1, int(max_args))
        args = self.subscription_args(inst_ids)
        return [args[start : start + limit] for start in range(0, len(args), limit)]

    def discover_usdt_perpetuals(self, *, timeout_s: float = 10.0) -> list[tuple[str, str]]:
        with httpx.Client(timeout=timeout_s) as client:
            response = client.get(
                f"{self.rest_base_url}/api/v5/public/instruments", params={"instType": "SWAP"}
            )
            response.raise_for_status()
            payload = response.json()
        if str(payload.get("code", "0")) != "0":
            raise RuntimeError(f"OKX instruments error: {payload.get('msg', 'unknown')}")
        data = payload.get("data")
        self.last_instrument_metadata = [
            dict(item) for item in data if isinstance(item, dict)
        ] if isinstance(data, list) else []
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
        public_args, business_args = self.subscription_groups(inst_ids)
        # OKX may change tick size / minimum trade amount while a collector is
        # running. Capture the public instruments stream once per connection so
        # the replay tape contains the exact rule changes effective at that time.
        public_args.append({"channel": "instruments", "instType": "SWAP"})

        streams = [
            self._messages_from_endpoint(
                self.ws_url,
                public_args,
                connection_prefix="okx-public",
            )
        ]
        if business_args:
            streams.append(
                self._messages_from_endpoint(
                    self.business_ws_url,
                    business_args,
                    connection_prefix="okx-business",
                )
            )
        pending = {
            asyncio.create_task(anext(stream)): stream for stream in streams
        }
        try:
            while pending:
                done, _ = await asyncio.wait(
                    pending, return_when=asyncio.FIRST_COMPLETED
                )
                for task in done:
                    stream = pending.pop(task)
                    try:
                        payload = task.result()
                    except StopAsyncIteration:
                        continue
                    yield payload
                    pending[asyncio.create_task(anext(stream))] = stream
        finally:
            for task in pending:
                task.cancel()
            await asyncio.gather(*pending, return_exceptions=True)
            await asyncio.gather(
                *(stream.aclose() for stream in streams),
                return_exceptions=True,
            )

    async def _messages_from_endpoint(
        self,
        url: str,
        args: list[dict[str, str]],
        *,
        connection_prefix: str,
    ) -> AsyncIterator[dict[str, object]]:
        """Run one independently reconnecting OKX public socket."""
        attempt = 0
        while True:
            try:
                connection_id = f"{connection_prefix}-{uuid.uuid4().hex}"
                session_started = time.monotonic()
                async with websockets.connect(url, ping_interval=20, ping_timeout=10) as socket:
                    for start in range(0, len(args), 100):
                        await socket.send(
                            json.dumps({"op": "subscribe", "args": args[start : start + 100]})
                        )
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
                            if time.monotonic() - session_started >= self.session_refresh_s:
                                break
            except asyncio.CancelledError:
                raise
            except Exception:
                delay = compute_backoff_delay(
                    attempt=attempt,
                    shard_key=f"{connection_prefix}-ws",
                )
                attempt += 1
                await asyncio.sleep(delay.delay_seconds)


__all__ = [
    "BUSINESS_WS_URL",
    "OkxMarketState",
    "OkxPublicClient",
    "PUBLIC_WS_URL",
    "REST_BASE_URL",
    "SCHEMA_VERSION",
    "okx_book_checksum",
    "parse_okx_swap_instruments",
]
