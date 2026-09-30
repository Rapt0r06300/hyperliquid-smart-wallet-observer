"""Post-collection reconciliation of public trade tapes.

Only exact event identifiers are compared. A venue is marked MATCHED only when the
public reference endpoint demonstrably covers the beginning of the captured window.
No aggregate-vs-individual trade substitution is allowed.
"""
from __future__ import annotations

import asyncio
import gzip
import json
import math
import time
from collections.abc import Iterable, Mapping
from pathlib import Path
from typing import Any

import httpx

HYPERLIQUID_INFO_BASE_WEIGHT = 20.0
DEFAULT_HYPERLIQUID_REFERENCE_BASE_WEIGHT_BUDGET_PER_MIN = 480.0


def safe_hyperliquid_reference_interval_s(
    coin_count: int,
    requested_interval_s: float,
    *,
    base_weight_budget_per_min: float = DEFAULT_HYPERLIQUID_REFERENCE_BASE_WEIGHT_BUDGET_PER_MIN,
) -> float:
    """Return a conservative poll cadence for Hyperliquid recentTrades.

    Hyperliquid applies an aggregate 1200 REST-weight/minute IP limit. recentTrades
    is an info request with base weight 20 and extra weight for returned rows. This
    guard budgets only 480 weight/minute to the base requests, deliberately leaving
    headroom for response-size weight and the other public reconciliation calls.
    """
    count = max(0, int(coin_count))
    requested = max(1.0, float(requested_interval_s))
    budget = max(1.0, float(base_weight_budget_per_min))
    if count <= 0:
        return requested
    minimum = (count * HYPERLIQUID_INFO_BASE_WEIGHT * 60.0) / budget
    return max(requested, float(math.ceil(minimum)))


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


class HyperliquidTradeReferenceSampler:
    """Continuously sample public recentTrades so long windows remain reconcilable.

    The REST sampler is independent from the WebSocket connection. Exact Hyperliquid
    trade IDs (tid) are accumulated with their exchange timestamps. No synthetic row
    is created when a poll fails.
    """

    def __init__(
        self,
        coins: Iterable[str],
        *,
        info_url: str = "https://api.hyperliquid.xyz/info",
        interval_s: float = 2.0,
        base_weight_budget_per_min: float = DEFAULT_HYPERLIQUID_REFERENCE_BASE_WEIGHT_BUDGET_PER_MIN,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self.coins = tuple(
            sorted({str(coin).strip().upper() for coin in coins if str(coin).strip()})
        )
        self.info_url = str(info_url)
        self.requested_interval_s = max(1.0, float(interval_s))
        self.base_weight_budget_per_min = max(1.0, float(base_weight_budget_per_min))
        self.interval_s = safe_hyperliquid_reference_interval_s(
            len(self.coins),
            self.requested_interval_s,
            base_weight_budget_per_min=self.base_weight_budget_per_min,
        )
        self._owns_client = client is None
        self.client = client or httpx.AsyncClient(timeout=10.0)
        self._lock = asyncio.Lock()
        self._rows: dict[str, dict[str, int]] = {coin: {} for coin in self.coins}
        self._success_wall_ms: dict[str, list[int]] = {coin: [] for coin in self.coins}
        self.poll_errors: dict[str, int] = {coin: 0 for coin in self.coins}
        self.polls = 0

    async def sample_once(self) -> None:
        async with self._lock:
            sampled_wall_ms = int(time.time() * 1_000)

            async def one(coin: str) -> None:
                try:
                    response = await self.client.post(
                        self.info_url,
                        json={"type": "recentTrades", "coin": coin},
                    )
                    response.raise_for_status()
                    payload = response.json()
                except Exception:
                    self.poll_errors[coin] += 1
                    return
                rows = payload if isinstance(payload, list) else []
                if not isinstance(rows, list):
                    self.poll_errors[coin] += 1
                    return
                accepted = 0
                for row in rows:
                    if not isinstance(row, Mapping):
                        continue
                    tid = row.get("tid")
                    ts = _int(row.get("time"))
                    if tid in {None, ""} or ts is None:
                        continue
                    self._rows[coin][str(tid)] = ts
                    accepted += 1
                # An empty but valid response is still a successful public poll.
                self._success_wall_ms[coin].append(sampled_wall_ms)
                if accepted:
                    # Bound retained history to the active process horizon. The
                    # caller owns a bounded collection job, so this remains finite.
                    pass

            await asyncio.gather(*(one(coin) for coin in self.coins))
            self.polls += 1

    async def run(self) -> None:
        await self.sample_once()
        while True:
            await asyncio.sleep(self.interval_s)
            await self.sample_once()

    async def close(self) -> None:
        if self._owns_client:
            await self.client.aclose()

    def stats(self) -> dict[str, Any]:
        estimated_base_weight = (
            (len(self.coins) * HYPERLIQUID_INFO_BASE_WEIGHT * 60.0) / self.interval_s
            if self.coins
            else 0.0
        )
        return {
            "polls": int(self.polls),
            "requested_interval_s": self.requested_interval_s,
            "effective_interval_s": self.interval_s,
            "base_weight_budget_per_min": self.base_weight_budget_per_min,
            "estimated_base_weight_per_min": round(estimated_base_weight, 3),
            "poll_errors": {coin: int(value) for coin, value in self.poll_errors.items()},
            "successful_polls": {
                coin: len(rows) for coin, rows in self._success_wall_ms.items()
            },
            "reference_trade_ids": {
                coin: len(rows) for coin, rows in self._rows.items()
            },
        }

    def reconcile(
        self,
        path: str | Path,
        *,
        symbol: str,
        start_ms: int,
        end_ms: int,
    ) -> dict[str, Any]:
        coin = str(symbol).strip().upper()
        live_ids, live_events = live_trade_ids(path, venue="hyperliquid")
        refs = self._rows.get(coin, {})
        ref_ids = {
            trade_id
            for trade_id, ts in refs.items()
            if int(start_ms) <= int(ts) <= int(end_ms)
        }
        reference_times = [
            int(ts)
            for ts in refs.values()
            if int(start_ms) <= int(ts) <= int(end_ms)
        ]
        all_reference_times = list(refs.values())
        if not self._success_wall_ms.get(coin):
            return {
                "status": "UNAVAILABLE",
                "reason": "HYPERLIQUID_REFERENCE_NO_SUCCESSFUL_POLL",
                "live_count": len(live_ids),
            }
        if live_ids and not ref_ids:
            return {
                "status": "PARTIAL",
                "reason": "HYPERLIQUID_REFERENCE_EMPTY_FOR_LIVE_WINDOW",
                "live_count": len(live_ids),
                "reference_count": 0,
            }

        # Coverage is provable when accumulated reference history reaches at least
        # the first and last live trade timestamps in the shard. Exact ID matching
        # then establishes completeness inside that covered interval.
        coverage_start = min(all_reference_times) if all_reference_times else None
        coverage_end = max(all_reference_times) if all_reference_times else None
        if live_ids and (
            coverage_start is None
            or coverage_end is None
            or coverage_start > int(start_ms)
            or coverage_end < int(end_ms)
        ):
            return {
                "status": "PARTIAL",
                "reason": "REFERENCE_DOES_NOT_COVER_WINDOW",
                "live_count": len(live_ids),
                "reference_count": len(ref_ids),
                "reference_first_ts_ms": coverage_start,
                "reference_last_ts_ms": coverage_end,
                "poll_errors": int(self.poll_errors.get(coin, 0)),
            }

        report = _compare(
            live_ids,
            ref_ids,
            live_event_count=live_events,
            reference_event_count=len(ref_ids),
            reference_coverage="ACCUMULATED_RECENT_TRADES",
        )
        report["poll_errors"] = int(self.poll_errors.get(coin, 0))
        report["successful_polls"] = len(self._success_wall_ms.get(coin, []))
        report["reference_first_ts_ms"] = (
            min(reference_times) if reference_times else None
        )
        report["reference_last_ts_ms"] = (
            max(reference_times) if reference_times else None
        )
        return report


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
    # Binance documents bounded time queries; keep every initial request below
    # one hour, then split again when a page is saturated.
    pending: list[tuple[int, int]] = []
    cursor = start
    max_interval_ms = 55 * 60 * 1_000
    while cursor <= end:
        right = min(end, cursor + max_interval_ms)
        pending.append((cursor, right))
        cursor = right + 1
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
    elif key == "hyperliquid":
        value = row.get("tid")
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
    "DEFAULT_HYPERLIQUID_REFERENCE_BASE_WEIGHT_BUDGET_PER_MIN",
    "HYPERLIQUID_INFO_BASE_WEIGHT",
    "HyperliquidTradeReferenceSampler",
    "safe_hyperliquid_reference_interval_s",
    "live_trade_ids",
    "reconcile_binance_aggtrade_shard",
    "reconcile_bybit_trade_shard",
    "reconcile_okx_trade_shard",
]
