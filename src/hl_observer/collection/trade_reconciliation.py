"""Post-collection reconciliation of public trade tapes.

Only exact event identifiers are compared. A venue is marked MATCHED only when the
public reference endpoint demonstrably covers the beginning of the captured window.
No aggregate-vs-individual trade substitution is allowed.
"""
from __future__ import annotations

import asyncio
import gzip
import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import httpx


def live_trade_ids(path: str | Path, *, venue: str) -> tuple[set[str], int]:
    ids: set[str] = set()
    event_count = 0
    with gzip.open(Path(path), "rt", encoding="utf-8") as handle:
        for line in handle:
            if not line.strip():
                continue
            record = json.loads(line)
            if not isinstance(record, Mapping):
                continue
            raw = record.get("raw_payload")
            if isinstance(raw, str):
                try:
                    raw = json.loads(raw)
                except json.JSONDecodeError:
                    continue
            if not isinstance(raw, Mapping):
                continue
            data = raw.get("data")
            if isinstance(data, list):
                rows = data
            elif isinstance(data, Mapping):
                rows = [data]
            elif str(venue).lower() == "binance":
                # Binance cloud envelopes preserve the raw stream payload itself.
                rows = [raw]
            else:
                rows = []
            for row in rows:
                if not isinstance(row, Mapping):
                    continue
                trade_id = _trade_id(row, venue)
                if trade_id is None:
                    continue
                event_count += 1
                ids.add(trade_id)
    return ids, event_count


async def reconcile_bybit_trade_shard(
    path: str | Path,
    *,
    symbol: str,
    start_ms: int,
    end_ms: int,
    client: httpx.AsyncClient | None = None,
    limit: int = 1000,
) -> dict[str, Any]:
    own_client = client is None
    http = client or httpx.AsyncClient(base_url="https://api.bybit.com", timeout=10.0)
    try:
        response = await http.get(
            "/v5/market/recent-trade",
            params={
                "category": "linear",
                "symbol": str(symbol).upper(),
                "limit": min(1000, max(1, int(limit))),
            },
        )
        response.raise_for_status()
        payload = response.json()
    except Exception as exc:
        return _error_report("BYBIT_REFERENCE_ERROR", exc)
    finally:
        if own_client:
            await http.aclose()

    if int(payload.get("retCode", -1)) != 0:
        return {
            "status": "UNAVAILABLE",
            "reason": "BYBIT_REFERENCE_REJECTED",
            "message": str(payload.get("retMsg") or ""),
        }
    result = payload.get("result")
    rows = result.get("list") if isinstance(result, Mapping) else None
    reference = [row for row in rows if isinstance(row, Mapping)] if isinstance(rows, list) else []
    timestamps = [_int(row.get("time")) for row in reference]
    present_ts = [value for value in timestamps if value is not None]
    if not present_ts or min(present_ts) > int(start_ms):
        return {
            "status": "PARTIAL",
            "reason": "REFERENCE_DOES_NOT_COVER_WINDOW_START",
            "reference_count": len(reference),
            "oldest_reference_ts_ms": min(present_ts) if present_ts else None,
        }

    ref_ids = {
        str(row.get("execId"))
        for row in reference
        if row.get("execId") not in {None, ""}
        and start_ms <= (_int(row.get("time")) or -1) <= end_ms
    }
    live_ids, live_events = live_trade_ids(path, venue="bybit")
    return _compare(
        live_ids,
        ref_ids,
        live_event_count=live_events,
        reference_event_count=len(ref_ids),
        reference_coverage="WINDOW_START_COVERED",
    )


async def reconcile_okx_trade_shard(
    path: str | Path,
    *,
    symbol: str,
    start_ms: int,
    end_ms: int,
    client: httpx.AsyncClient | None = None,
    limit: int = 100,
    max_pages: int = 200,
) -> dict[str, Any]:
    own_client = client is None
    http = client or httpx.AsyncClient(base_url="https://www.okx.com", timeout=10.0)
    rows: list[Mapping[str, Any]] = []
    cursor = int(end_ms) + 1
    covered_start = False
    try:
        for _page in range(max(1, int(max_pages))):
            response = await http.get(
                "/api/v5/market/history-trades",
                params={
                    "instId": str(symbol).upper(),
                    "type": "2",
                    "after": str(cursor),
                    "limit": str(min(100, max(1, int(limit)))),
                },
            )
            response.raise_for_status()
            payload = response.json()
            if str(payload.get("code", "0")) != "0":
                return {
                    "status": "UNAVAILABLE",
                    "reason": "OKX_REFERENCE_REJECTED",
                    "message": str(payload.get("msg") or ""),
                }
            page = payload.get("data")
            page_rows = [row for row in page if isinstance(row, Mapping)] if isinstance(page, list) else []
            if not page_rows:
                break
            rows.extend(page_rows)
            timestamps = [_int(row.get("ts")) for row in page_rows]
            present = [value for value in timestamps if value is not None]
            if not present:
                break
            oldest = min(present)
            if oldest <= int(start_ms):
                covered_start = True
                break
            if oldest >= cursor:
                break
            cursor = oldest
    except Exception as exc:
        return _error_report("OKX_REFERENCE_ERROR", exc)
    finally:
        if own_client:
            await http.aclose()

    if not covered_start:
        return {
            "status": "PARTIAL",
            "reason": "REFERENCE_DOES_NOT_COVER_WINDOW_START",
            "reference_count": len(rows),
            "oldest_reference_ts_ms": min(
                (_int(row.get("ts")) for row in rows),
                default=None,
            ),
        }

    ref_ids = {
        str(row.get("tradeId"))
        for row in rows
        if row.get("tradeId") not in {None, ""}
        and start_ms <= (_int(row.get("ts")) or -1) <= end_ms
    }
    live_ids, live_events = live_trade_ids(path, venue="okx")
    return _compare(
        live_ids,
        ref_ids,
        live_event_count=live_events,
        reference_event_count=len(ref_ids),
        reference_coverage="WINDOW_START_COVERED",
    )



async def reconcile_binance_aggtrade_shard(
    path: str | Path,
    *,
    symbol: str,
    start_ms: int,
    end_ms: int,
    client: httpx.AsyncClient | None = None,
    limit: int = 1000,
    max_requests: int = 240,
    throttle_s: float = 0.55,
) -> dict[str, Any]:
    """Reconcile Binance aggregate-trade WS ids against public REST aggTrades.

    REST supports explicit bounded time windows. Full pages are recursively split
    until each interval is demonstrably exhausted; hitting the request budget
    remains PARTIAL instead of silently claiming completeness.
    """
    own_client = client is None
    http = client or httpx.AsyncClient(base_url="https://fapi.binance.com", timeout=10.0)
    start = int(start_ms)
    end = int(end_ms)
    if end < start:
        if own_client:
            await http.aclose()
        return {"status": "UNAVAILABLE", "reason": "INVALID_WINDOW"}

    reference: dict[str, Mapping[str, Any]] = {}
    pending: list[tuple[int, int]] = [(start, end)]
    requests = 0
    try:
        while pending:
            left, right = pending.pop()
            if requests >= max(1, int(max_requests)):
                return {
                    "status": "PARTIAL",
                    "reason": "REFERENCE_REQUEST_BUDGET_EXHAUSTED",
                    "reference_count": len(reference),
                    "requests": requests,
                }
            response = await http.get(
                "/fapi/v1/aggTrades",
                params={
                    "symbol": str(symbol).upper(),
                    "startTime": left,
                    "endTime": right,
                    "limit": min(1000, max(1, int(limit))),
                },
            )
            requests += 1
            response.raise_for_status()
            payload = response.json()
            if not isinstance(payload, list):
                return {
                    "status": "UNAVAILABLE",
                    "reason": "BINANCE_REFERENCE_INVALID",
                    "requests": requests,
                }
            rows = [row for row in payload if isinstance(row, Mapping)]
            for row in rows:
                trade_id = row.get("a")
                ts = _int(row.get("T"))
                if trade_id not in {None, ""} and ts is not None and start <= ts <= end:
                    reference[str(trade_id)] = row

            if len(rows) >= min(1000, max(1, int(limit))) and left < right:
                midpoint = left + (right - left) // 2
                if midpoint <= left:
                    return {
                        "status": "PARTIAL",
                        "reason": "REFERENCE_DENSITY_UNRESOLVED",
                        "reference_count": len(reference),
                        "requests": requests,
                    }
                pending.append((midpoint + 1, right))
                pending.append((left, midpoint))
            if throttle_s > 0 and pending:
                await asyncio.sleep(float(throttle_s))
    except Exception as exc:
        return _error_report("BINANCE_REFERENCE_ERROR", exc)
    finally:
        if own_client:
            await http.aclose()

    live_ids, live_events = live_trade_ids(path, venue="binance")
    return _compare(
        live_ids,
        set(reference),
        live_event_count=live_events,
        reference_event_count=len(reference),
        reference_coverage="EXPLICIT_BOUNDED_REST_WINDOW",
    )


def _compare(
    live_ids: set[str],
    reference_ids: set[str],
    *,
    live_event_count: int,
    reference_event_count: int,
    reference_coverage: str,
) -> dict[str, Any]:
    missing = reference_ids - live_ids
    live_only = live_ids - reference_ids
    matched = live_ids & reference_ids
    status = "MATCHED" if not missing and not live_only else (
        "PARTIAL" if matched else "MISMATCH"
    )
    return {
        "status": status,
        "live_count": len(live_ids),
        "live_event_count": int(live_event_count),
        "reference_count": len(reference_ids),
        "reference_event_count": int(reference_event_count),
        "matched_count": len(matched),
        "missing_from_live": len(missing),
        "live_only": len(live_only),
        "duplicate_live_keys": max(0, int(live_event_count) - len(live_ids)),
        "reference_coverage": reference_coverage,
    }


def _trade_id(row: Mapping[str, Any], venue: str) -> str | None:
    key = str(venue).lower()
    if key == "bybit":
        value = row.get("i", row.get("execId"))
    elif key == "okx":
        value = row.get("tradeId")
    elif key == "binance":
        value = row.get("a")
    else:
        return None
    return None if value in {None, ""} else str(value)


def _error_report(reason: str, exc: Exception) -> dict[str, Any]:
    return {
        "status": "UNAVAILABLE",
        "reason": reason,
        "error": f"{type(exc).__name__}: {exc}"[:500],
    }


def _int(value: Any) -> int | None:
    try:
        return int(value) if value is not None and not isinstance(value, bool) else None
    except (TypeError, ValueError, OverflowError):
        return None


__all__ = [
    "live_trade_ids",
    "reconcile_binance_aggtrade_shard",
    "reconcile_bybit_trade_shard",
    "reconcile_okx_trade_shard",
]
