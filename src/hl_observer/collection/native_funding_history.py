"""Authoritative public funding-rate history for native Bybit and OKX lanes."""
from __future__ import annotations

import asyncio
import time
from collections.abc import Iterable, Mapping
from typing import Any

import httpx

from hl_observer.collection.tick_dataset import TickEnvelope
from hl_observer.realtime.feed_quality import FeedEventKind

BYBIT_REST = "https://api.bybit.com"
OKX_REST = "https://www.okx.com"


async def fetch_bybit_funding_settlements(
    symbols: Iterable[str],
    *,
    start_ms: int,
    end_ms: int,
    rest_base_url: str = BYBIT_REST,
    http_client: httpx.AsyncClient | None = None,
    concurrency: int = 6,
) -> list[TickEnvelope]:
    start, end = int(start_ms), int(end_ms)
    if start >= end:
        return []
    wanted = _symbols(symbols)
    if not wanted:
        return []

    owns = http_client is None
    client = http_client or httpx.AsyncClient(
        base_url=rest_base_url.rstrip("/"),
        timeout=10.0,
    )
    semaphore = asyncio.Semaphore(max(1, int(concurrency)))

    async def one(symbol: str) -> list[TickEnvelope]:
        sent = int(time.time() * 1000)
        async with semaphore:
            response = await client.get(
                "/v5/market/funding/history",
                params={
                    "category": "linear",
                    "symbol": symbol,
                    "startTime": start,
                    "endTime": end,
                    "limit": 200,
                },
            )
        response.raise_for_status()
        recv_mono = time.monotonic_ns()
        recv_wall = int(time.time() * 1000)
        payload = response.json()
        if int(payload.get("retCode", -1)) != 0:
            raise RuntimeError(f"Bybit funding error: {payload.get('retMsg', 'unknown')}")
        result = payload.get("result")
        rows = result.get("list") if isinstance(result, Mapping) else None
        by_time: dict[int, Mapping[str, Any]] = {}
        if isinstance(rows, list):
            for raw in rows:
                if not isinstance(raw, Mapping):
                    continue
                ts = _int(raw.get("fundingRateTimestamp"))
                rate = _float(raw.get("fundingRate"))
                if ts is None or rate is None or not start <= ts <= end:
                    continue
                if not -1.0 < rate < 1.0:
                    continue
                by_time[ts] = raw
        return [
            _envelope(
                source_id="bybit_public_rest",
                symbol=str(raw.get("symbol") or symbol).upper(),
                timestamp=ts,
                sequence=index,
                raw=raw,
                rate=float(raw["fundingRate"]),
                realized_rate=None,
                rest_url=f"{rest_base_url.rstrip('/')}/v5/market/funding/history",
                sent_wall_ms=sent,
                receive_wall_ms=recv_wall,
                receive_mono_ns=recv_mono,
                start_ms=start,
                end_ms=end,
            )
            for index, (ts, raw) in enumerate(sorted(by_time.items()), start=1)
        ]

    try:
        nested = await asyncio.gather(*(one(symbol) for symbol in wanted))
    finally:
        if owns:
            await client.aclose()
    return _sort([row for group in nested for row in group])


async def fetch_okx_funding_settlements(
    symbols: Iterable[str],
    *,
    start_ms: int,
    end_ms: int,
    rest_base_url: str = OKX_REST,
    http_client: httpx.AsyncClient | None = None,
    concurrency: int = 6,
) -> list[TickEnvelope]:
    start, end = int(start_ms), int(end_ms)
    if start >= end:
        return []
    wanted = _symbols(symbols)
    if not wanted:
        return []

    owns = http_client is None
    client = http_client or httpx.AsyncClient(
        base_url=rest_base_url.rstrip("/"),
        timeout=10.0,
    )
    semaphore = asyncio.Semaphore(max(1, int(concurrency)))

    async def one(symbol: str) -> list[TickEnvelope]:
        sent = int(time.time() * 1000)
        async with semaphore:
            response = await client.get(
                "/api/v5/public/funding-rate-history",
                params={
                    "instId": symbol,
                    # OKX returns newest first. A run window is bounded and far
                    # below the 400-row public page limit, so one page suffices.
                    "before": str(start - 1),
                    "after": str(end + 1),
                    "limit": "400",
                },
            )
        response.raise_for_status()
        recv_mono = time.monotonic_ns()
        recv_wall = int(time.time() * 1000)
        payload = response.json()
        if str(payload.get("code", "-1")) != "0":
            raise RuntimeError(f"OKX funding error: {payload.get('msg', 'unknown')}")
        rows = payload.get("data")
        by_time: dict[int, Mapping[str, Any]] = {}
        if isinstance(rows, list):
            for raw in rows:
                if not isinstance(raw, Mapping):
                    continue
                ts = _int(raw.get("fundingTime"))
                rate = _float(raw.get("fundingRate"))
                if ts is None or rate is None or not start <= ts <= end:
                    continue
                if not -1.0 < rate < 1.0:
                    continue
                by_time[ts] = raw
        return [
            _envelope(
                source_id="okx_public_rest",
                symbol=str(raw.get("instId") or symbol).upper(),
                timestamp=ts,
                sequence=index,
                raw=raw,
                rate=float(raw["fundingRate"]),
                realized_rate=_float(raw.get("realizedRate")),
                rest_url=f"{rest_base_url.rstrip('/')}/api/v5/public/funding-rate-history",
                sent_wall_ms=sent,
                receive_wall_ms=recv_wall,
                receive_mono_ns=recv_mono,
                start_ms=start,
                end_ms=end,
            )
            for index, (ts, raw) in enumerate(sorted(by_time.items()), start=1)
        ]

    try:
        nested = await asyncio.gather(*(one(symbol) for symbol in wanted))
    finally:
        if owns:
            await client.aclose()
    return _sort([row for group in nested for row in group])


def _envelope(
    *,
    source_id: str,
    symbol: str,
    timestamp: int,
    sequence: int,
    raw: Mapping[str, Any],
    rate: float,
    realized_rate: float | None,
    rest_url: str,
    sent_wall_ms: int,
    receive_wall_ms: int,
    receive_mono_ns: int,
    start_ms: int,
    end_ms: int,
) -> TickEnvelope:
    return TickEnvelope(
        source_id=source_id,
        channel="funding_settlement",
        instrument=symbol,
        event_kind=FeedEventKind.EVENT,
        raw_payload=dict(raw),
        exchange_ts_ms=int(timestamp),
        received_ts_ms=int(receive_wall_ms),
        local_monotonic_ns=int(receive_mono_ns),
        connection_id=None,
        sequence=int(sequence),
        provenance={
            "url": rest_url,
            "network": "mainnet",
            "access": "read_only",
            "transport": "https",
            "authenticated": False,
            "request_start_ms": int(start_ms),
            "request_end_ms": int(end_ms),
            "request_send_wall_ms": int(sent_wall_ms),
            "request_receive_wall_ms": int(receive_wall_ms),
        },
        parsed_summary={
            "funding_rate": float(rate),
            "realized_rate": realized_rate,
            "authoritative_history": True,
            "data_gate_ready": True,
        },
    )


def _symbols(values: Iterable[str]) -> tuple[str, ...]:
    return tuple(sorted({str(value).strip().upper() for value in values if str(value).strip()}))


def _sort(rows: list[TickEnvelope]) -> list[TickEnvelope]:
    return sorted(
        rows,
        key=lambda item: (
            int(item.exchange_ts_ms or 0),
            str(item.instrument),
            int(item.sequence or 0),
        ),
    )


def _int(value: Any) -> int | None:
    try:
        return int(value) if value is not None else None
    except (TypeError, ValueError, OverflowError):
        return None


def _float(value: Any) -> float | None:
    try:
        return float(value) if value is not None else None
    except (TypeError, ValueError, OverflowError):
        return None


__all__ = [
    "BYBIT_REST",
    "OKX_REST",
    "fetch_bybit_funding_settlements",
    "fetch_okx_funding_settlements",
]
