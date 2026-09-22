"""Run-level SAFE coverage evidence for Alina Dataset V2.

Shard quality answers whether one shard is trustworthy. Replay coverage answers the
separate question: do all required families overlap in time for this symbol/venue?
No missing family is inferred or zero-filled.
"""
from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable, Mapping
from typing import Any

from hl_observer.collection.native_venue_market import canonical_coin


def build_safe_coverage_matrix(
    manifests: Iterable[Mapping[str, Any]],
) -> dict[str, Any]:
    """Aggregate only remotely verified SAFE manifests by coin/venue/family."""
    grouped: dict[
        tuple[str, str, str],
        list[tuple[int, int, int, int, str]],
    ] = defaultdict(list)

    for raw in manifests:
        if raw.get("quality_status") != "SAFE":
            continue
        if raw.get("validation_allowed") is not True:
            continue
        if raw.get("asset_verified") is not True:
            continue
        venue = str(raw.get("venue") or "").strip().lower()
        family = str(raw.get("family") or "").strip()
        symbol = str(raw.get("symbol") or "").strip().upper()
        coin = canonical_coin(symbol)
        start = _int(raw.get("start_ts_ms"))
        end = _int(raw.get("end_ts_ms"))
        events = _int(raw.get("event_count"))
        size = _int(raw.get("bytes"))
        dataset_id = str(raw.get("dataset_id") or "")
        if (
            not venue
            or not family
            or not symbol
            or not coin
            or start is None
            or end is None
            or end < start
            or events is None
            or events <= 0
            or size is None
            or size <= 0
            or not dataset_id
        ):
            continue
        grouped[(coin, venue, family)].append(
            (start, end, events, size, dataset_id)
        )

    rows: list[dict[str, Any]] = []
    for (coin, venue, family), spans in sorted(grouped.items()):
        merged = _merge_intervals((start, end) for start, end, *_rest in spans)
        rows.append(
            {
                "coin": coin,
                "venue": venue,
                "family": family,
                "shard_count": len(spans),
                "event_count": sum(row[2] for row in spans),
                "bytes": sum(row[3] for row in spans),
                "start_ts_ms": min(row[0] for row in spans),
                "end_ts_ms": max(row[1] for row in spans),
                "covered_ms": sum(end - start for start, end in merged),
                "intervals": [
                    {"start_ts_ms": start, "end_ts_ms": end}
                    for start, end in merged
                ],
                "dataset_ids": [row[4] for row in sorted(spans)],
            }
        )

    return {
        "schema": "alina.safe_coverage_matrix.v1",
        "safe_partitions": len(rows),
        "coins": sorted({row["coin"] for row in rows}),
        "venues": sorted({row["venue"] for row in rows}),
        "families": sorted({row["family"] for row in rows}),
        "rows": rows,
    }


def assess_replay_contract(
    matrix: Mapping[str, Any],
    *,
    coin: str,
    requirements: Mapping[str, Iterable[str]],
    min_overlap_ms: int = 1,
) -> dict[str, Any]:
    """Prove a common SAFE time interval across required venue/family sets."""
    target_coin = canonical_coin(coin)
    required: dict[str, tuple[str, ...]] = {
        str(venue).strip().lower(): tuple(
            sorted({str(family).strip() for family in families if str(family).strip()})
        )
        for venue, families in requirements.items()
        if str(venue).strip()
    }
    if not target_coin or not required or any(not families for families in required.values()):
        return {
            "schema": "alina.replay_coverage_contract.v1",
            "coin": target_coin,
            "status": "NO_GO",
            "overlap_start_ts_ms": None,
            "overlap_end_ts_ms": None,
            "overlap_ms": 0,
            "missing": ["INVALID_REQUIREMENTS"],
        }

    lookup: dict[tuple[str, str], list[tuple[int, int]]] = defaultdict(list)
    for raw in matrix.get("rows") or []:
        if not isinstance(raw, Mapping):
            continue
        if canonical_coin(str(raw.get("coin") or "")) != target_coin:
            continue
        venue = str(raw.get("venue") or "").lower()
        family = str(raw.get("family") or "")
        for interval in raw.get("intervals") or []:
            if not isinstance(interval, Mapping):
                continue
            start = _int(interval.get("start_ts_ms"))
            end = _int(interval.get("end_ts_ms"))
            if start is not None and end is not None and end >= start:
                lookup[(venue, family)].append((start, end))

    missing: list[str] = []
    interval_sets: list[list[tuple[int, int]]] = []
    for venue, families in sorted(required.items()):
        for family in families:
            intervals = _merge_intervals(lookup.get((venue, family), ()))
            if not intervals:
                missing.append(f"{venue}:{family}")
            else:
                interval_sets.append(intervals)

    if missing:
        return {
            "schema": "alina.replay_coverage_contract.v1",
            "coin": target_coin,
            "status": "NO_GO",
            "requirements": {k: list(v) for k, v in required.items()},
            "overlap_start_ts_ms": None,
            "overlap_end_ts_ms": None,
            "overlap_ms": 0,
            "missing": missing,
        }

    overlap = _intersect_many(interval_sets)
    best = max(overlap, key=lambda item: item[1] - item[0], default=None)
    overlap_ms = 0 if best is None else max(0, best[1] - best[0])
    ready = best is not None and overlap_ms >= max(1, int(min_overlap_ms))
    return {
        "schema": "alina.replay_coverage_contract.v1",
        "coin": target_coin,
        "status": "READY" if ready else "NO_GO",
        "requirements": {k: list(v) for k, v in required.items()},
        "overlap_start_ts_ms": best[0] if best else None,
        "overlap_end_ts_ms": best[1] if best else None,
        "overlap_ms": overlap_ms,
        "all_overlaps": [
            {"start_ts_ms": start, "end_ts_ms": end, "overlap_ms": end - start}
            for start, end in overlap
        ],
        "missing": [],
    }


def _merge_intervals(intervals: Iterable[tuple[int, int]]) -> list[tuple[int, int]]:
    rows = sorted(
        (int(start), int(end))
        for start, end in intervals
        if int(end) >= int(start)
    )
    if not rows:
        return []
    merged: list[list[int]] = [[rows[0][0], rows[0][1]]]
    for start, end in rows[1:]:
        current = merged[-1]
        if start <= current[1]:
            current[1] = max(current[1], end)
        else:
            merged.append([start, end])
    return [(start, end) for start, end in merged]


def _intersect_many(
    interval_sets: Iterable[Iterable[tuple[int, int]]],
) -> list[tuple[int, int]]:
    sets = [list(rows) for rows in interval_sets]
    if not sets:
        return []
    current = _merge_intervals(sets[0])
    for rows in sets[1:]:
        right = _merge_intervals(rows)
        next_rows: list[tuple[int, int]] = []
        i = j = 0
        while i < len(current) and j < len(right):
            start = max(current[i][0], right[j][0])
            end = min(current[i][1], right[j][1])
            if end >= start:
                next_rows.append((start, end))
            if current[i][1] < right[j][1]:
                i += 1
            else:
                j += 1
        current = _merge_intervals(next_rows)
        if not current:
            break
    return current


def _int(value: Any) -> int | None:
    try:
        return int(value) if value is not None and not isinstance(value, bool) else None
    except (TypeError, ValueError, OverflowError):
        return None


__all__ = ["assess_replay_contract", "build_safe_coverage_matrix"]
