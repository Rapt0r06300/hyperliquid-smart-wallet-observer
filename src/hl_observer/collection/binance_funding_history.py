"""Read-only Binance USD-M realized-funding history for replay PnL."""
from __future__ import annotations

import asyncio
import time
from collections.abc import Iterable, Mapping
from typing import Any

import httpx

from hl_observer.collection.tick_dataset import TickEnvelope
from hl_observer.realtime.feed_quality import FeedEventKind

REST_BASE_URL = "https://fapi.binance.com"


async def fetch_binance_funding_settlements(
    symbols: Iterable[str],
    *,
    start_ms: int,
    end_ms: int,
    rest_base_url: str = REST_BASE_URL,
    http_client: httpx.AsyncClient | None = None,
    concurrency: int = 6,
) -> list[TickEnvelope]:
    start = int(start_ms)
    end = int(end_ms)
    if start >= end:
        return []
    wanted = tuple(
        sorted({str(symbol).strip().upper() for symbol in symbols if str(symbol).strip()})
    )
    if not wanted:
        return []

    owns_client = http_client is None
    client = http_client or httpx.AsyncClient(
        base_url=rest_base_url.rstrip("/"),
        timeout=10.0,
    )
    semaphore = asyncio.Semaphore(max(1, int(concurrency)))

    async def one(symbol: str) -> list[TickEnvelope]:
        cursor = start
        rows_by_time: dict[int, Mapping[str, Any]] = {}
        request_round = 0
        while cursor <= end:
            request_round += 1
            sent_wall_ms = int(time.time() * 1000)
            async with semaphore:
                response = await client.get(
                    "/fapi/v1/fundingRate",
                    params={
                        "symbol": symbol,
                        "startTime": cursor,
                        "endTime": end,
                        "limit": 1000,
                    },
                )
            response.raise_for_status()
            receive_mono_ns = time.monotonic_ns()
            receive_wall_ms = int(time.time() * 1000)
            payload = response.json()
            if not isinstance(payload, list) or not payload:
                break

            accepted_times: list[int] = []
            for raw in payload:
                if not isinstance(raw, Mapping):
                    continue
                try:
                    ts = int(raw.get("fundingTime"))
                    funding = float(raw.get("fundingRate"))
                except (TypeError, ValueError, OverflowError):
                    continue
                if ts < start or ts > end:
                    continue
                if not (-1.0 < funding < 1.0):
                    continue
                rows_by_time[ts] = {
                    **dict(raw),
                    "_request_send_wall_ms": sent_wall_ms,
                    "_request_receive_wall_ms": receive_wall_ms,
                    "_request_round": request_round,
                    "_receive_mono_ns": receive_mono_ns,
                }
                accepted_times.append(ts)

            if len(payload) < 1000:
                break
            latest = max(accepted_times, default=cursor - 1)
            if latest < cursor:
                break
            cursor = latest + 1

        result: list[TickEnvelope] = []
        for sequence, ts in enumerate(sorted(rows_by_time), start=1):
            stored = dict(rows_by_time[ts])
            sent_wall_ms = int(stored.pop("_request_send_wall_ms"))
            receive_wall_ms = int(stored.pop("_request_receive_wall_ms"))
            request_round = int(stored.pop("_request_round"))
            receive_mono_ns = int(stored.pop("_receive_mono_ns"))
            rate = float(stored["fundingRate"])
            result.append(
                TickEnvelope(
                    source_id="binance_usdm_public_rest",
                    channel="funding_settlement",
                    instrument=str(stored.get("symbol") or symbol).upper(),
                    event_kind=FeedEventKind.EVENT,
                    raw_payload=stored,
                    exchange_ts_ms=ts,
                    received_ts_ms=receive_wall_ms,
                    local_monotonic_ns=receive_mono_ns,
                    connection_id=None,
                    sequence=sequence,
                    provenance={
                        "url": f"{rest_base_url.rstrip('/')}/fapi/v1/fundingRate",
                        "network": "mainnet",
                        "access": "read_only",
                        "transport": "https",
                        "authenticated": False,
                        "request_start_ms": start,
                        "request_end_ms": end,
                        "request_round": request_round,
                        "request_send_wall_ms": sent_wall_ms,
                        "request_receive_wall_ms": receive_wall_ms,
                    },
                    parsed_summary={
                        "funding_rate": rate,
                        "mark_price": _float(stored.get("markPrice")),
                        "rate_type": stored.get("rateType"),
                        "authoritative_history": True,
                        "data_gate_ready": True,
                    },
                )
            )
        return result

    try:
        nested = await asyncio.gather(*(one(symbol) for symbol in wanted))
    finally:
        if owns_client:
            await client.aclose()

    rows = [envelope for group in nested for envelope in group]
    rows.sort(
        key=lambda item: (
            int(item.exchange_ts_ms or 0),
            str(item.instrument),
            int(item.sequence or 0),
        )
    )
    return rows


def _float(value: Any) -> float | None:
    try:
        return float(value) if value is not None else None
    except (TypeError, ValueError, OverflowError):
        return None


__all__ = ["REST_BASE_URL", "fetch_binance_funding_settlements"]
