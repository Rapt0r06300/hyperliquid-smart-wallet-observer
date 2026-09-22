"""Run-level SAFE coverage matrix for Alina Dataset V2.

This module is intentionally descriptive only: it indexes remotely verified SAFE
shards by canonical coin, venue and family. Strategy replay eligibility remains
owned by strategy_data_contracts + cross_venue_window, which additionally enforce
same-run provenance, exact instrument mapping and pair synchronization.
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
        "authoritative_for_replay": False,
        "strategy_gate": "strategy_data_contracts+cross_venue_window",
        "safe_partitions": len(rows),
        "coins": sorted({row["coin"] for row in rows}),
        "venues": sorted({row["venue"] for row in rows}),
        "families": sorted({row["family"] for row in rows}),
        "rows": rows,
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


def _int(value: Any) -> int | None:
    try:
        return int(value) if value is not None and not isinstance(value, bool) else None
    except (TypeError, ValueError, OverflowError):
        return None


__all__ = ["build_safe_coverage_matrix"]
