"""Post-collection reconciliation of public trade tapes.

Only exact event identifiers are compared. A venue is marked MATCHED only when the
public reference endpoint demonstrably covers the beginning of the captured window.
No aggregate-vs-individual trade substitution is allowed.
"""
from __future__ import annotations

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
            if not isinstance(raw, Mapping):
                continue
            data = raw.get("data")
            rows = data if isinstance(data, list) else [data] if isinstance(data, Mapping) else []
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
    "reconcile_bybit_trade_shard",
    "reconcile_okx_trade_shard",
]
