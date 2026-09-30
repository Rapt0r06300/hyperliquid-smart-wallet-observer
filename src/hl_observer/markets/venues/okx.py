"""Native read-only OKX V5 public market-data adapter."""

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
from hl_observer.markets.venues.symbols import canonical_okx_symbol, canonical_symbol

OKX_REST_BASE = "https://openapi.okx.com"
OKX_WS_PUBLIC = "wss://ws.okx.com:8443/ws/v5/public"


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


def parse_okx_instrument(raw: dict[str, Any]) -> VenueInstrument | None:
    inst_id = str(raw.get("instId") or "").upper()
    inst_type = str(raw.get("instType") or "").upper()
    state = str(raw.get("state") or "").lower()
    ct_type = str(raw.get("ctType") or "").lower()
    settle = str(raw.get("settleCcy") or "").upper()
    if not inst_id or inst_type != "SWAP" or settle != "USDT" or ct_type != "linear":
        return None
    if state not in {"live", "preopen"}:
        return None
    parts = inst_id.split("-")
    if len(parts) < 3 or parts[-1] != "SWAP":
        return None
    base, quote = parts[0], parts[1]
    return VenueInstrument(
        venue="okx",
        symbol=inst_id,
        base=base,
        quote=quote,
        canonical_symbol=canonical_symbol(base, quote),
        status=state,
        contract_type="perpetual",
        is_prelaunch=state == "preopen",
        tick_size=_float(raw.get("tickSz")),
        min_size=_float(raw.get("minSz")),
    )


def parse_okx_bbo(payload: dict[str, Any], *, received_ts_ms: int | None = None) -> VenueQuote | None:
    arg = payload.get("arg")
    rows = payload.get("data")
    if not isinstance(arg, dict) or not isinstance(rows, list) or not rows:
        return None
    if str(arg.get("channel") or "") != "bbo-tbt":
        return None
    row = rows[0] if isinstance(rows[0], dict) else None
    if row is None:
        return None
    bids = row.get("bids")
    asks = row.get("asks")
    if not isinstance(bids, list) or not bids or not isinstance(asks, list) or not asks:
        return None
    try:
        bid_price, bid_size = float(bids[0][0]), float(bids[0][1])
        ask_price, ask_size = float(asks[0][0]), float(asks[0][1])
    except (IndexError, TypeError, ValueError):
        return None
    inst_id = str(arg.get("instId") or "").upper()
    if not inst_id or bid_price <= 0 or ask_price <= 0 or bid_size < 0 or ask_size < 0:
        return None
    now_ms = received_ts_ms if received_ts_ms is not None else int(time.time() * 1000)
    return VenueQuote(
        venue="okx",
        symbol=inst_id,
        canonical_symbol=canonical_okx_symbol(inst_id),
        bid_price=bid_price,
        bid_size=bid_size,
        ask_price=ask_price,
        ask_size=ask_size,
        exchange_ts_ms=_int(row.get("ts")),
        received_ts_ms=now_ms,
        sequence=_int(row.get("seqId")),
    )


def parse_okx_metrics(
    ticker: dict[str, Any],
    *,
    funding: dict[str, Any] | None = None,
    open_interest: dict[str, Any] | None = None,
) -> VenueMetrics | None:
    inst_id = str(ticker.get("instId") or "").upper()
    if not inst_id:
        return None
    funding = funding or {}
    open_interest = open_interest or {}
    return VenueMetrics(
        venue="okx",
        symbol=inst_id,
        canonical_symbol=canonical_okx_symbol(inst_id),
        last_price=_float(ticker.get("last")),
        volume_24h=_float(ticker.get("vol24h")),
        turnover_24h=_float(ticker.get("volCcy24h")),
        open_interest=_float(open_interest.get("oi")),
        open_interest_value=_float(open_interest.get("oiCcy")),
        funding_rate=_float(funding.get("fundingRate")),
        next_funding_time_ms=_int(funding.get("nextFundingTime")),
        exchange_ts_ms=_int(ticker.get("ts")),
    )


class OkxPublicClient:
    """Public-only OKX adapter; deliberately contains no auth/order methods."""

    venue = "okx"

    def __init__(self, *, http_client: httpx.AsyncClient | None = None, timeout_seconds: float = 10.0) -> None:
        self._owns_http = http_client is None
        self._http = http_client or httpx.AsyncClient(base_url=OKX_REST_BASE, timeout=timeout_seconds)

    async def __aenter__(self) -> OkxPublicClient:
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
        if not isinstance(payload, dict) or str(payload.get("code", "-1")) != "0":
            raise RuntimeError(f"OKX public API error: {str(payload)[:240]}")
        return payload

    async def discover_instruments(self, *, include_prelaunch: bool = False) -> list[VenueInstrument]:
        payload = await self._get("/api/v5/public/instruments", params={"instType": "SWAP"})
        rows = payload.get("data") if isinstance(payload.get("data"), list) else []
        items: list[VenueInstrument] = []
        for row in rows:
            if not isinstance(row, dict):
                continue
            item = parse_okx_instrument(row)
            if item is None or (item.is_prelaunch and not include_prelaunch):
                continue
            items.append(item)
        return sorted(items, key=lambda item: item.symbol)

    async def fetch_metrics(self, symbol: str) -> VenueMetrics | None:
        inst_id = str(symbol).upper()
        ticker_payload, funding_payload, oi_payload = await asyncio.gather(
            self._get("/api/v5/market/ticker", params={"instId": inst_id}),
            self._get("/api/v5/public/funding-rate", params={"instId": inst_id}),
            self._get("/api/v5/public/open-interest", params={"instType": "SWAP", "instId": inst_id}),
        )
        ticker_rows = ticker_payload.get("data") if isinstance(ticker_payload.get("data"), list) else []
        funding_rows = funding_payload.get("data") if isinstance(funding_payload.get("data"), list) else []
        oi_rows = oi_payload.get("data") if isinstance(oi_payload.get("data"), list) else []
        if not ticker_rows or not isinstance(ticker_rows[0], dict):
            return None
        return parse_okx_metrics(
            ticker_rows[0],
            funding=funding_rows[0] if funding_rows and isinstance(funding_rows[0], dict) else None,
            open_interest=oi_rows[0] if oi_rows and isinstance(oi_rows[0], dict) else None,
        )

    @staticmethod
    def subscription_payload(symbols: list[str]) -> dict[str, Any]:
        return {
            "op": "subscribe",
            "args": [
                {"channel": "bbo-tbt", "instId": symbol.upper()}
                for symbol in symbols
            ],
        }

    async def iter_bbo(self, symbols: list[str]) -> AsyncIterator[VenueQuote]:
        clean = sorted({str(symbol).strip().upper() for symbol in symbols if str(symbol).strip()})
        if not clean:
            return
        attempt = 0
        while True:
            try:
                async with websockets.connect(
                    OKX_WS_PUBLIC,
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
                        if payload.get("event") in {"error", "notice"}:
                            if payload.get("event") == "notice" and str(payload.get("code")) == "64008":
                                await websocket.close()
                                break
                            continue
                        quote = parse_okx_bbo(payload)
                        if quote is not None and not quote.is_crossed:
                            yield quote
            except (OSError, ConnectionClosed):
                attempt += 1
                await asyncio.sleep(min(30.0, float(2 ** min(attempt, 5))))


__all__ = [
    "OKX_REST_BASE",
    "OKX_WS_PUBLIC",
    "OkxPublicClient",
    "parse_okx_bbo",
    "parse_okx_instrument",
    "parse_okx_metrics",
]
