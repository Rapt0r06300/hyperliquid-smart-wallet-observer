"""Native read-only Bybit V5 public market-data adapter."""

from __future__ import annotations

import asyncio
import json
import time
from collections.abc import AsyncIterator
from typing import Any

import httpx
import websockets
from websockets.exceptions import ConnectionClosed

from hl_observer.markets.venues.models import VenueInstrument, VenueMetrics, VenueQuote
from hl_observer.markets.venues.symbols import canonical_bybit_symbol, canonical_symbol

BYBIT_REST_BASE = "https://api.bybit.com"
BYBIT_WS_LINEAR = "wss://stream.bybit.com/v5/public/linear"


def _float(value: Any) -> float | None:
    if value in (None, ""):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _int(value: Any) -> int | None:
    if value in (None, ""):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def parse_bybit_instrument(raw: dict[str, Any]) -> VenueInstrument | None:
    symbol = str(raw.get("symbol") or "").upper()
    base = str(raw.get("baseCoin") or "").upper()
    quote = str(raw.get("quoteCoin") or "").upper()
    status = str(raw.get("status") or "")
    contract_type = str(raw.get("contractType") or "")
    if not symbol or not base or quote != "USDT" or contract_type != "LinearPerpetual":
        return None
    if status not in {"Trading", "PreLaunch"}:
        return None
    price_filter = raw.get("priceFilter") if isinstance(raw.get("priceFilter"), dict) else {}
    lot_filter = raw.get("lotSizeFilter") if isinstance(raw.get("lotSizeFilter"), dict) else {}
    return VenueInstrument(
        venue="bybit",
        symbol=symbol,
        base=base,
        quote=quote,
        canonical_symbol=canonical_symbol(base, quote),
        status=status,
        contract_type="perpetual",
        is_prelaunch=status == "PreLaunch",
        tick_size=_float(price_filter.get("tickSize")),
        min_size=_float(lot_filter.get("minOrderQty")),
    )


def parse_bybit_bbo(payload: dict[str, Any], *, received_ts_ms: int | None = None) -> VenueQuote | None:
    data = payload.get("data")
    if not isinstance(data, dict):
        return None
    bids = data.get("b")
    asks = data.get("a")
    if not isinstance(bids, list) or not bids or not isinstance(asks, list) or not asks:
        return None
    try:
        bid_price, bid_size = float(bids[0][0]), float(bids[0][1])
        ask_price, ask_size = float(asks[0][0]), float(asks[0][1])
    except (IndexError, TypeError, ValueError):
        return None
    symbol = str(data.get("s") or "").upper()
    if not symbol or bid_price <= 0 or ask_price <= 0 or bid_size < 0 or ask_size < 0:
        return None
    now_ms = received_ts_ms if received_ts_ms is not None else int(time.time() * 1000)
    exchange_ts = _int(data.get("cts")) or _int(payload.get("ts"))
    return VenueQuote(
        venue="bybit",
        symbol=symbol,
        canonical_symbol=canonical_bybit_symbol(symbol),
        bid_price=bid_price,
        bid_size=bid_size,
        ask_price=ask_price,
        ask_size=ask_size,
        exchange_ts_ms=exchange_ts,
        received_ts_ms=now_ms,
        sequence=_int(data.get("seq")) or _int(data.get("u")),
    )


def parse_bybit_metrics(raw: dict[str, Any]) -> VenueMetrics | None:
    symbol = str(raw.get("symbol") or "").upper()
    if not symbol:
        return None
    return VenueMetrics(
        venue="bybit",
        symbol=symbol,
        canonical_symbol=canonical_bybit_symbol(symbol),
        last_price=_float(raw.get("lastPrice")),
        mark_price=_float(raw.get("markPrice")),
        index_price=_float(raw.get("indexPrice")),
        volume_24h=_float(raw.get("volume24h")),
        turnover_24h=_float(raw.get("turnover24h")),
        open_interest=_float(raw.get("openInterest")),
        open_interest_value=_float(raw.get("openInterestValue")),
        funding_rate=_float(raw.get("fundingRate")),
        next_funding_time_ms=_int(raw.get("nextFundingTime")),
    )


class BybitPublicClient:
    """Public-only Bybit adapter; deliberately contains no auth/order methods."""

    venue = "bybit"

    def __init__(self, *, http_client: httpx.AsyncClient | None = None, timeout_seconds: float = 10.0) -> None:
        self._owns_http = http_client is None
        self._http = http_client or httpx.AsyncClient(base_url=BYBIT_REST_BASE, timeout=timeout_seconds)

    async def __aenter__(self) -> BybitPublicClient:
        return self

    async def __aexit__(self, *_exc: object) -> None:
        await self.close()

    async def close(self) -> None:
        if self._owns_http:
            await self._http.aclose()

    async def _get(self, path: str, *, params: dict[str, Any]) -> dict[str, Any]:
        response = await self._http.get(path, params=params)
        response.raise_for_status()
        payload = response.json()
        if not isinstance(payload, dict) or int(payload.get("retCode", -1)) != 0:
            raise RuntimeError(f"Bybit public API error: {str(payload)[:240]}")
        return payload

    async def _instrument_page(self, *, status: str | None = None) -> list[dict[str, Any]]:
        cursor = ""
        rows: list[dict[str, Any]] = []
        while True:
            params: dict[str, Any] = {"category": "linear", "limit": 1000}
            if status:
                params["status"] = status
            if cursor:
                params["cursor"] = cursor
            payload = await self._get("/v5/market/instruments-info", params=params)
            result = payload.get("result") if isinstance(payload.get("result"), dict) else {}
            page = result.get("list") if isinstance(result.get("list"), list) else []
            rows.extend(row for row in page if isinstance(row, dict))
            cursor = str(result.get("nextPageCursor") or "")
            if not cursor:
                return rows

    async def discover_instruments(self, *, include_prelaunch: bool = False) -> list[VenueInstrument]:
        rows = await self._instrument_page()
        if include_prelaunch:
            rows.extend(await self._instrument_page(status="PreLaunch"))
        unique: dict[str, VenueInstrument] = {}
        for row in rows:
            item = parse_bybit_instrument(row)
            if item is None or (item.is_prelaunch and not include_prelaunch):
                continue
            unique[item.symbol] = item
        return sorted(unique.values(), key=lambda item: item.symbol)

    async def fetch_metrics(self, symbol: str) -> VenueMetrics | None:
        payload = await self._get(
            "/v5/market/tickers",
            params={"category": "linear", "symbol": str(symbol).upper()},
        )
        result = payload.get("result") if isinstance(payload.get("result"), dict) else {}
        rows = result.get("list") if isinstance(result.get("list"), list) else []
        return parse_bybit_metrics(rows[0]) if rows and isinstance(rows[0], dict) else None

    @staticmethod
    def subscription_payload(symbols: list[str]) -> dict[str, Any]:
        return {"op": "subscribe", "args": [f"orderbook.1.{symbol.upper()}" for symbol in symbols]}

    async def iter_bbo(self, symbols: list[str]) -> AsyncIterator[VenueQuote]:
        clean = sorted({str(symbol).strip().upper() for symbol in symbols if str(symbol).strip()})
        if not clean:
            return
        attempt = 0
        while True:
            try:
                async with websockets.connect(
                    BYBIT_WS_LINEAR,
                    ping_interval=20,
                    ping_timeout=20,
                    close_timeout=5,
                    max_size=2**20,
                ) as websocket:
                    await websocket.send(json.dumps(self.subscription_payload(clean)))
                    attempt = 0
                    async for raw in websocket:
                        try:
                            payload = json.loads(raw)
                        except (json.JSONDecodeError, TypeError):
                            continue
                        if not isinstance(payload, dict):
                            continue
                        quote = parse_bybit_bbo(payload)
                        if quote is not None and not quote.is_crossed:
                            yield quote
            except (OSError, ConnectionClosed):
                attempt += 1
                await asyncio.sleep(min(30.0, float(2 ** min(attempt, 5))))


__all__ = [
    "BYBIT_REST_BASE",
    "BYBIT_WS_LINEAR",
    "BybitPublicClient",
    "parse_bybit_bbo",
    "parse_bybit_instrument",
    "parse_bybit_metrics",
]
