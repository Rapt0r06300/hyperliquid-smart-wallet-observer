"""Public Binance USD-M market-context collector for replay evidence.

High-frequency book data lives on the /public endpoint and is collected elsewhere.
This module uses the 2026 /market endpoint for regular market streams and public REST
for open interest + exchange metadata. No authentication, account or order endpoint.
"""
from __future__ import annotations

import asyncio
import json
import time
import uuid
from collections.abc import Callable, Iterable, Mapping
from typing import Any

import httpx
import websockets

from hl_observer.collection.tick_dataset import TickEnvelope
from hl_observer.realtime.feed_quality import FeedEventKind

REST_BASE_URL = "https://fapi.binance.com"
WS_MARKET_BASE_URL = "wss://fstream.binance.com/market/stream"
SCHEMA_VERSION = "alina.binance_usdm_market_context.v1"


def parse_market_frame(payload: Mapping[str, Any]) -> dict[str, Any] | None:
    raw = payload.get("data") if isinstance(payload.get("data"), Mapping) else payload
    if not isinstance(raw, Mapping):
        return None
    event_type = str(raw.get("e") or "")
    if event_type == "markPriceUpdate":
        symbol = str(raw.get("s") or "").upper()
        if not symbol:
            return None
        return {
            "channel": "mark_funding",
            "symbol": symbol,
            "exchange_ts_ms": _int(raw.get("E")),
            "sequence": None,
            "summary": {
                "mark_price": _float(raw.get("p")),
                "index_price": _float(raw.get("i")),
                "estimated_settle_price": _float(raw.get("P")),
                "funding_rate": _float(raw.get("r")),
                "next_funding_time_ms": _int(raw.get("T")),
                "mark_moving_average": _float(raw.get("ap")),
            },
            "raw": dict(raw),
        }
    if event_type == "24hrTicker":
        symbol = str(raw.get("s") or "").upper()
        if not symbol:
            return None
        return {
            "channel": "ticker",
            "symbol": symbol,
            "exchange_ts_ms": _int(raw.get("E")),
            "sequence": None,
            "summary": {
                "last_price": _float(raw.get("c")),
                "base_volume_24h": _float(raw.get("v")),
                "quote_volume_24h": _float(raw.get("q")),
                "trade_count_24h": _int(raw.get("n")),
            },
            "raw": dict(raw),
        }
    if event_type == "forceOrder":
        order = raw.get("o")
        if not isinstance(order, Mapping):
            return None
        symbol = str(order.get("s") or "").upper()
        if not symbol:
            return None
        return {
            "channel": "liquidations",
            "symbol": symbol,
            "exchange_ts_ms": _int(order.get("T")) or _int(raw.get("E")),
            "sequence": None,
            "summary": {
                "side": str(order.get("S") or ""),
                "order_type": str(order.get("o") or ""),
                "time_in_force": str(order.get("f") or ""),
                "quantity": _float(order.get("q")),
                "price": _float(order.get("p")),
                "average_price": _float(order.get("ap")),
                "last_filled_quantity": _float(order.get("l")),
                "filled_accumulated_quantity": _float(order.get("z")),
                "status": str(order.get("X") or ""),
            },
            "raw": dict(raw),
        }
    return None


def instrument_metadata(
    payload: Mapping[str, Any],
    *,
    wanted_symbols: Iterable[str] = (),
) -> list[dict[str, Any]]:
    wanted = {str(value).upper() for value in wanted_symbols if str(value).strip()}
    rows = payload.get("symbols")
    if not isinstance(rows, list):
        return []
    result: list[dict[str, Any]] = []
    for row in rows:
        if not isinstance(row, Mapping):
            continue
        symbol = str(row.get("symbol") or "").upper()
        if not symbol or (wanted and symbol not in wanted):
            continue
        filters = {
            str(item.get("filterType") or ""): dict(item)
            for item in (row.get("filters") or [])
            if isinstance(item, Mapping)
        }
        price_filter = filters.get("PRICE_FILTER", {})
        lot_filter = filters.get("LOT_SIZE", {})
        min_notional_filter = (
            filters.get("MIN_NOTIONAL", {})
            or filters.get("NOTIONAL", {})
        )
        result.append(
            {
                "symbol": symbol,
                "pair": str(row.get("pair") or ""),
                "contract_type": str(row.get("contractType") or ""),
                "status": str(row.get("status") or ""),
                "base_asset": str(row.get("baseAsset") or ""),
                "quote_asset": str(row.get("quoteAsset") or ""),
                "margin_asset": str(row.get("marginAsset") or ""),
                "onboard_date": _int(row.get("onboardDate")),
                "delivery_date": _int(row.get("deliveryDate")),
                "price_precision": _int(row.get("pricePrecision")),
                "quantity_precision": _int(row.get("quantityPrecision")),
                "tick_size": _float(price_filter.get("tickSize")),
                "min_price": _float(price_filter.get("minPrice")),
                "max_price": _float(price_filter.get("maxPrice")),
                "lot_size": _float(lot_filter.get("stepSize")),
                "min_qty": _float(lot_filter.get("minQty")),
                "max_qty": _float(lot_filter.get("maxQty")),
                "min_notional": _float(
                    min_notional_filter.get(
                        "notional",
                        min_notional_filter.get("minNotional"),
                    )
                ),
                "raw": dict(row),
            }
        )
    return result


class BinanceMarketContextCollector:
    def __init__(
        self,
        symbols: Iterable[str],
        *,
        rest_base_url: str = REST_BASE_URL,
        ws_market_base_url: str = WS_MARKET_BASE_URL,
        open_interest_interval_s: float = 30.0,
        metadata_interval_s: float = 1800.0,
        http_client: httpx.AsyncClient | None = None,
        tick_sink: Callable[[TickEnvelope], Any] | None = None,
        context_sink: Callable[[str, Mapping[str, Any]], Any] | None = None,
        clock_sync_provider: Callable[[], Mapping[str, Any]] | None = None,
    ) -> None:
        self.symbols = tuple(
            sorted({str(value).strip().upper() for value in symbols if str(value).strip()})
        )
        self.rest_base_url = rest_base_url.rstrip("/")
        self.ws_market_base_url = ws_market_base_url.rstrip("/")
        self.open_interest_interval_s = max(5.0, float(open_interest_interval_s))
        self.metadata_interval_s = max(60.0, float(metadata_interval_s))
        self._owns_http = http_client is None
        self.http = http_client or httpx.AsyncClient(
            base_url=self.rest_base_url,
            timeout=10.0,
        )
        self.tick_sink = tick_sink
        self.context_sink = context_sink
        self.clock_sync_provider = clock_sync_provider
        self.latest: dict[str, dict[str, Any]] = {}
        self.frames = 0
        self.open_interest_samples = 0
        self.metadata_samples = 0
        self.reconnects = 0
        self.rest_failures = 0
        self.last_error = ""

    def websocket_url(self) -> str:
        streams = []
        for symbol in self.symbols:
            lower = symbol.lower()
            streams.extend(
                (
                    f"{lower}@markPrice@1s",
                    f"{lower}@ticker",
                    f"{lower}@forceOrder",
                )
            )
        return f"{self.ws_market_base_url}?streams={'/'.join(streams)}"

    async def close(self) -> None:
        if self._owns_http:
            await self.http.aclose()

    async def run(self) -> None:
        if not self.symbols:
            return
        try:
            await asyncio.gather(
                self.run_market_ws(),
                self.run_open_interest(),
                self.run_metadata(),
            )
        finally:
            await self.close()

    async def run_market_ws(self) -> None:
        attempt = 0
        while True:
            connection_id = f"bin-market-{uuid.uuid4().hex}"
            try:
                async with websockets.connect(
                    self.websocket_url(),
                    ping_interval=20,
                    ping_timeout=10,
                    close_timeout=5,
                    max_size=2**23,
                ) as socket:
                    attempt = 0
                    async for raw_text in socket:
                        receive_mono_ns = time.monotonic_ns()
                        receive_wall_ms = int(time.time() * 1_000)
                        try:
                            payload = json.loads(raw_text)
                        except (TypeError, ValueError):
                            continue
                        if not isinstance(payload, Mapping):
                            continue
                        parsed = parse_market_frame(payload)
                        if parsed is None or parsed["symbol"] not in self.symbols:
                            continue
                        self.frames += 1
                        symbol = parsed["symbol"]
                        current = self.latest.setdefault(symbol, {})
                        current.update(parsed["summary"])
                        current["receive_ts_ms"] = receive_wall_ms
                        current["exchange_ts_ms"] = parsed["exchange_ts_ms"]
                        self._emit_context(symbol, current)
                        self._emit_tick(
                            TickEnvelope(
                                source_id="binance_usdm_public",
                                channel=parsed["channel"],
                                instrument=symbol,
                                event_kind=FeedEventKind.EVENT,
                                raw_payload=parsed["raw"],
                                exchange_ts_ms=parsed["exchange_ts_ms"],
                                received_ts_ms=receive_wall_ms,
                                local_monotonic_ns=receive_mono_ns,
                                connection_id=connection_id,
                                sequence=parsed["sequence"],
                                provenance={
                                    "url": self.websocket_url(),
                                    "network": "mainnet",
                                    "access": "read_only",
                                    "transport": "websocket",
                                    "authenticated": False,
                                },
                                parsed_summary={
                                    **self._clock_evidence(),
                                    **parsed["summary"],
                                    "data_gate_ready": False,
                                },
                            )
                        )
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                self.reconnects += 1
                self.last_error = f"{type(exc).__name__}: {exc}"[:500]
                await asyncio.sleep(min(30.0, 2.0 ** min(attempt, 5)))
                attempt += 1

    async def run_open_interest(self) -> None:
        while True:
            await self.poll_open_interest_once()
            await asyncio.sleep(self.open_interest_interval_s)

    async def poll_open_interest_once(self) -> int:
        semaphore = asyncio.Semaphore(8)

        async def one(symbol: str) -> int:
            async with semaphore:
                sent = int(time.time() * 1_000)
                try:
                    response = await self.http.get(
                        "/fapi/v1/openInterest",
                        params={"symbol": symbol},
                    )
                    response.raise_for_status()
                    payload = response.json()
                except Exception as exc:
                    self.rest_failures += 1
                    self.last_error = f"{type(exc).__name__}: {exc}"[:500]
                    return 0
                receive_mono_ns = time.monotonic_ns()
                receive_wall_ms = int(time.time() * 1_000)
                exchange_ts_ms = _int(payload.get("time"))
                oi = _float(payload.get("openInterest"))
                if oi is None:
                    return 0
                current = self.latest.setdefault(symbol, {})
                current["open_interest"] = oi
                current["open_interest_receive_ts_ms"] = receive_wall_ms
                self._emit_context(symbol, current)
                self._emit_tick(
                    TickEnvelope(
                        source_id="binance_usdm_public",
                        channel="open_interest",
                        instrument=symbol,
                        event_kind=FeedEventKind.SNAPSHOT,
                        raw_payload=payload,
                        exchange_ts_ms=exchange_ts_ms,
                        received_ts_ms=receive_wall_ms,
                        local_monotonic_ns=receive_mono_ns,
                        connection_id=None,
                        sequence=None,
                        provenance={
                            "url": f"{self.rest_base_url}/fapi/v1/openInterest",
                            "network": "mainnet",
                            "access": "read_only",
                            "transport": "https",
                            "authenticated": False,
                            "request_send_wall_ms": sent,
                            "request_receive_wall_ms": receive_wall_ms,
                        },
                        parsed_summary={
                            **self._clock_evidence(),
                            "open_interest": oi,
                            "data_gate_ready": False,
                        },
                    )
                )
                self.open_interest_samples += 1
                return 1

        return sum(await asyncio.gather(*(one(symbol) for symbol in self.symbols)))

    async def run_metadata(self) -> None:
        while True:
            await self.poll_metadata_once()
            await asyncio.sleep(self.metadata_interval_s)

    async def poll_metadata_once(self) -> int:
        sent = int(time.time() * 1_000)
        try:
            response = await self.http.get("/fapi/v1/exchangeInfo")
            response.raise_for_status()
            payload = response.json()
        except Exception as exc:
            self.rest_failures += 1
            self.last_error = f"{type(exc).__name__}: {exc}"[:500]
            return 0
        receive_mono_ns = time.monotonic_ns()
        receive_wall_ms = int(time.time() * 1_000)
        exchange_ts_ms = _int(payload.get("serverTime"))
        rows = instrument_metadata(payload, wanted_symbols=self.symbols)
        for row in rows:
            symbol = row["symbol"]
            current = self.latest.setdefault(symbol, {})
            current["instrument_metadata"] = {
                key: value for key, value in row.items() if key != "raw"
            }
            self._emit_context(symbol, current)
            self._emit_tick(
                TickEnvelope(
                    source_id="binance_usdm_public",
                    channel="instrument_metadata",
                    instrument=symbol,
                    event_kind=FeedEventKind.SNAPSHOT,
                    raw_payload=row["raw"],
                    exchange_ts_ms=exchange_ts_ms,
                    received_ts_ms=receive_wall_ms,
                    local_monotonic_ns=receive_mono_ns,
                    connection_id=None,
                    sequence=None,
                    provenance={
                        "url": f"{self.rest_base_url}/fapi/v1/exchangeInfo",
                        "network": "mainnet",
                        "access": "read_only",
                        "transport": "https",
                        "authenticated": False,
                        "request_send_wall_ms": sent,
                        "request_receive_wall_ms": receive_wall_ms,
                    },
                    parsed_summary={
                        **self._clock_evidence(),
                        **{key: value for key, value in row.items() if key != "raw"},
                        "data_gate_ready": False,
                    },
                )
            )
            self.metadata_samples += 1
        return len(rows)

    def _clock_evidence(self) -> dict[str, Any]:
        if self.clock_sync_provider is None:
            return {}
        try:
            row = self.clock_sync_provider()
        except Exception:
            return {}
        return dict(row) if isinstance(row, Mapping) else {}

    def health(self) -> dict[str, Any]:
        return {
            "schema_version": SCHEMA_VERSION,
            "symbols": len(self.symbols),
            "frames": self.frames,
            "open_interest_samples": self.open_interest_samples,
            "metadata_samples": self.metadata_samples,
            "reconnects": self.reconnects,
            "rest_failures": self.rest_failures,
            "latest_symbols": len(self.latest),
            "last_error": self.last_error,
            "clock_sync": self._clock_evidence(),
            "read_only": True,
            "real_execution": False,
        }

    def _emit_tick(self, envelope: TickEnvelope) -> None:
        if self.tick_sink is not None:
            self.tick_sink(envelope)

    def _emit_context(self, symbol: str, row: Mapping[str, Any]) -> None:
        if self.context_sink is not None:
            self.context_sink(symbol, dict(row))


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


__all__ = [
    "BinanceMarketContextCollector",
    "REST_BASE_URL",
    "SCHEMA_VERSION",
    "WS_MARKET_BASE_URL",
    "instrument_metadata",
    "parse_market_frame",
]
