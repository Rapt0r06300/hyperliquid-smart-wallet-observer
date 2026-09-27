"""Read-only Hyperliquid realized-funding collection for replay PnL.

The public fundingHistory endpoint is authoritative for realized hourly funding.
This module fetches a bounded collection window and emits one replayable envelope
per realized settlement. Missing/invalid rows are dropped rather than zero-filled.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import time
from collections.abc import Iterable, Mapping
from typing import Any

import httpx

from hl_observer.collection.tick_dataset import TickEnvelope
from hl_observer.realtime.feed_quality import FeedEventKind

INFO_URL = "https://api.hyperliquid.xyz/info"


async def fetch_hyperliquid_funding_settlements(
    coins: Iterable[str],
    *,
    start_ms: int,
    end_ms: int,
    info_url: str = INFO_URL,
    http_client: httpx.AsyncClient | None = None,
    concurrency: int = 6,
) -> list[TickEnvelope]:
    start = int(start_ms)
    end = int(end_ms)
    if start >= end:
        return []
    symbols = tuple(
        sorted({str(coin).strip() for coin in coins if str(coin).strip()})
    )
    if not symbols:
        return []

    owns_client = http_client is None
    client = http_client or httpx.AsyncClient(timeout=10.0)
    semaphore = asyncio.Semaphore(max(1, int(concurrency)))

    async def one(coin: str) -> list[TickEnvelope]:
        body = {
            "type": "fundingHistory",
            "coin": coin,
            "startTime": start,
            "endTime": end,
        }
        sent_wall_ms = int(time.time() * 1000)
        async with semaphore:
            response = await client.post(info_url, json=body)
        response.raise_for_status()
        receive_mono_ns = time.monotonic_ns()
        receive_wall_ms = int(time.time() * 1000)
        payload = response.json()
        if not isinstance(payload, list):
            return []

        by_time: dict[int, Mapping[str, Any]] = {}
        rejected_rows = 0
        duplicate_rows = 0
        for raw in payload:
            if not isinstance(raw, Mapping):
                rejected_rows += 1
                continue
            try:
                ts = int(raw.get("time"))
                funding = float(raw.get("fundingRate"))
            except (TypeError, ValueError, OverflowError):
                rejected_rows += 1
                continue
            if ts < start or ts > end:
                rejected_rows += 1
                continue
            if not (-1.0 < funding < 1.0):
                rejected_rows += 1
                continue
            if ts in by_time:
                duplicate_rows += 1
            by_time[ts] = raw

        coverage = {
            "schema": "alina.hyperliquid_funding_coverage.v1",
            "coin": coin,
            "request_start_ms": start,
            "request_end_ms": end,
            "response_rows": len(payload),
            "accepted_rows": len(by_time),
            "rejected_rows": rejected_rows,
            "duplicate_timestamp_rows": duplicate_rows,
            "pagination_complete": False,
            "coverage_status": "UNPROVEN_SINGLE_REQUEST_NO_PAGINATION",
            "data_gate_ready": False,
        }
        coverage["receipt_digest"] = hashlib.sha256(
            json.dumps(coverage, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()
        result: list[TickEnvelope] = []
        for sequence, ts in enumerate(sorted(by_time), start=1):
            raw = dict(by_time[ts])
            try:
                premium = (
                    float(raw["premium"])
                    if raw.get("premium") not in (None, "")
                    else None
                )
            except (TypeError, ValueError, OverflowError):
                premium = None
            result.append(
                TickEnvelope(
                    source_id="hyperliquid_public_rest",
                    channel="funding_settlement",
                    instrument=str(raw.get("coin") or coin).upper(),
                    event_kind=FeedEventKind.EVENT,
                    raw_payload=raw,
                    exchange_ts_ms=ts,
                    received_ts_ms=receive_wall_ms,
                    local_monotonic_ns=receive_mono_ns,
                    connection_id=None,
                    sequence=sequence,
                    provenance={
                        "url": info_url,
                        "network": "mainnet",
                        "access": "read_only",
                        "transport": "https",
                        "authenticated": False,
                        "request_type": "fundingHistory",
                        "request_start_ms": start,
                        "request_end_ms": end,
                        "request_send_wall_ms": sent_wall_ms,
                        "request_receive_wall_ms": receive_wall_ms,
                        "coverage_receipt": coverage,
                    },
                    parsed_summary={
                        "funding_rate": float(raw["fundingRate"]),
                        "premium": premium,
                        "authoritative_history": True,
                        "data_gate_ready": False,
                        "coverage_status": coverage["coverage_status"],
                        "coverage_receipt_digest": coverage["receipt_digest"],
                    },
                )
            )
        return result

    try:
        nested = await asyncio.gather(*(one(coin) for coin in symbols))
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


__all__ = ["INFO_URL", "fetch_hyperliquid_funding_settlements"]
