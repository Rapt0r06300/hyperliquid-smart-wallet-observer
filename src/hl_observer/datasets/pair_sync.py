"""Pairwise synchronization evidence for replay-grade cross-venue windows."""
from __future__ import annotations

import bisect
import gzip
import json
from collections.abc import Iterable, Mapping
from pathlib import Path
from typing import Any


def synchronization_points(
    records: Iterable[Mapping[str, Any]],
) -> list[dict[str, float | int | None]]:
    """Extract ordered timing points without fabricating missing exchange clocks."""
    points: list[dict[str, float | int | None]] = []
    for row in records:
        receive = _int(row.get("received_ts_ms", row.get("receive_ts_ms")))
        if receive is None:
            continue
        exchange = _int(row.get("exchange_ts_ms"))
        summary = row.get("parsed_summary")
        summary_map = summary if isinstance(summary, Mapping) else {}
        offset = _float(
            row.get("clock_offset_ms", summary_map.get("clock_offset_ms"))
        )
        corrected_exchange: float | None = None
        if exchange is not None and offset is not None:
            corrected_exchange = float(exchange) - float(offset)
        points.append(
            {
                "receive_ts_ms": receive,
                "exchange_corrected_ts_ms": corrected_exchange,
            }
        )
    return sorted(points, key=lambda row: int(row["receive_ts_ms"] or 0))


def load_sync_points(
    paths: Iterable[str | Path],
) -> list[dict[str, float | int | None]]:
    rows: list[dict[str, Any]] = []
    for raw_path in paths:
        path = Path(raw_path)
        if not path.is_file():
            continue
        opener = gzip.open if path.suffix == ".gz" else open
        with opener(path, "rt", encoding="utf-8") as handle:
            for line in handle:
                if not line.strip():
                    continue
                try:
                    row = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if isinstance(row, Mapping):
                    rows.append(dict(row))
    return synchronization_points(rows)


def build_pair_sync_report(
    left_points: Iterable[Mapping[str, Any]],
    right_points: Iterable[Mapping[str, Any]],
    *,
    max_match_distance_ms: float = 1_000.0,
) -> dict[str, Any]:
    """Match every left observation to the nearest unused right observation.

    Matching is one-to-one and bounded. Receive-clock evidence is always measured
    when both rows have reception timestamps. Corrected exchange-clock evidence is
    measured only when both rows carry explicit clock-offset evidence.
    """
    left = synchronization_points(left_points)
    right = synchronization_points(right_points)
    if not left or not right:
        return _empty_report("NO_DATA")

    right_receive = [int(row["receive_ts_ms"] or 0) for row in right]
    used: set[int] = set()
    receive_skews: list[float] = []
    exchange_skews: list[float] = []
    unmatched_left = 0

    for lrow in left:
        lrecv = int(lrow["receive_ts_ms"] or 0)
        insertion = bisect.bisect_left(right_receive, lrecv)
        candidates = []
        for index in (insertion - 1, insertion, insertion + 1):
            if 0 <= index < len(right) and index not in used:
                candidates.append(index)
        if not candidates:
            unmatched_left += 1
            continue
        best = min(
            candidates,
            key=lambda index: abs(right_receive[index] - lrecv),
        )
        skew = abs(float(right_receive[best]) - float(lrecv))
        if skew > float(max_match_distance_ms):
            unmatched_left += 1
            continue
        used.add(best)
        receive_skews.append(skew)

        lex = _float(lrow.get("exchange_corrected_ts_ms"))
        rex = _float(right[best].get("exchange_corrected_ts_ms"))
        if lex is not None and rex is not None:
            exchange_skews.append(abs(lex - rex))

    unmatched_right = max(0, len(right) - len(used))
    if not receive_skews:
        return {
            **_empty_report("NO_MATCH"),
            "left_count": len(left),
            "right_count": len(right),
            "unmatched_left": unmatched_left,
            "unmatched_right": unmatched_right,
        }

    receive_stats = _stats(receive_skews)
    exchange_stats = _stats(exchange_skews)
    status = "MATCHED" if unmatched_left == 0 and unmatched_right == 0 else "PARTIAL"
    return {
        "schema": "alina.pair_sync.v1",
        "status": status,
        "sample_count": len(receive_skews),
        "left_count": len(left),
        "right_count": len(right),
        "unmatched_left": unmatched_left,
        "unmatched_right": unmatched_right,
        "match_coverage_left": round(len(receive_skews) / len(left), 6),
        "match_coverage_right": round(len(receive_skews) / len(right), 6),
        "p50_receive_skew_ms": receive_stats["p50"],
        "p95_receive_skew_ms": receive_stats["p95"],
        "max_receive_skew_ms": receive_stats["max"],
        "exchange_sync_sample_count": len(exchange_skews),
        "p50_exchange_skew_ms": exchange_stats["p50"],
        "p95_exchange_skew_ms": exchange_stats["p95"],
        "max_exchange_skew_ms": exchange_stats["max"],
        "gap_count": unmatched_left + unmatched_right,
    }


def _empty_report(status: str) -> dict[str, Any]:
    return {
        "schema": "alina.pair_sync.v1",
        "status": status,
        "sample_count": 0,
        "left_count": 0,
        "right_count": 0,
        "unmatched_left": 0,
        "unmatched_right": 0,
        "match_coverage_left": 0.0,
        "match_coverage_right": 0.0,
        "p50_receive_skew_ms": None,
        "p95_receive_skew_ms": None,
        "max_receive_skew_ms": None,
        "exchange_sync_sample_count": 0,
        "p50_exchange_skew_ms": None,
        "p95_exchange_skew_ms": None,
        "max_exchange_skew_ms": None,
        "gap_count": 0,
    }


def _stats(values: Iterable[float]) -> dict[str, float | None]:
    rows = sorted(float(value) for value in values)
    if not rows:
        return {"p50": None, "p95": None, "max": None}

    def percentile(fraction: float) -> float:
        index = min(
            len(rows) - 1,
            max(0, int(round((len(rows) - 1) * fraction))),
        )
        return round(rows[index], 6)

    return {
        "p50": percentile(0.50),
        "p95": percentile(0.95),
        "max": round(rows[-1], 6),
    }


def _int(value: Any) -> int | None:
    try:
        return int(value) if value is not None and not isinstance(value, bool) else None
    except (TypeError, ValueError, OverflowError):
        return None


def _float(value: Any) -> float | None:
    try:
        return float(value) if value is not None and not isinstance(value, bool) else None
    except (TypeError, ValueError, OverflowError):
        return None


__all__ = [
    "build_pair_sync_report",
    "load_sync_points",
    "synchronization_points",
]
