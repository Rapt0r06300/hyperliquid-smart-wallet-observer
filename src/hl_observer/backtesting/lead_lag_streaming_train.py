"""Memory-bounded TRAIN diagnostics for Binance-led ETH shocks.

The canonical queue replay needs event timestamps, but loading every historical
trade at once can exhaust workstation memory.  This module scans immutable BBO
shards sequentially and keeps only the active rolling window plus scalar shock
statistics.  It is research-only and has no network or execution surface.
"""

from __future__ import annotations

import bisect
import gzip
import hashlib
import json
import math
from collections import deque
from collections.abc import Iterable, Iterator, Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from hl_observer.backtesting.lead_lag_source_alignment import (
    SourceWindow,
    discover_market_tick_windows,
    select_aligned_bbo_sources,
)

THRESHOLD_GRID_BPS = (4.0, 6.0, 8.0, 10.0, 12.0, 16.0, 20.0)
_FEASIBILITY_CACHE: dict[str, dict[str, Any]] = {}


def _lines(path: Path) -> Iterator[str]:
    opener = gzip.open if path.suffix == ".gz" else open
    try:
        with opener(path, "rt", encoding="utf-8", errors="ignore") as handle:
            yield from handle
    except OSError:
        return


def _finite(value: object) -> float | None:
    try:
        result = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return result if math.isfinite(result) else None


def _wall_ms(record: dict[str, Any]) -> int | None:
    for key in (
        "ts_wall_ms",
        "recv_wall_ts_ms",
        "received_ts_ms",
        "written_ts_ms",
        "write_wall_ts_ms",
        "snapshot_wall_ts_ms",
    ):
        value = _finite(record.get(key))
        if value is not None and value >= 1_500_000_000_000:
            return int(value)
    collected = _finite(record.get("collecte_ts"))
    if collected is not None and collected >= 1_500_000_000:
        return int(collected * 1000.0)
    return None


def _merge_ranges(windows: Iterable[SourceWindow]) -> list[tuple[int, int]]:
    merged: list[list[int]] = []
    for row in sorted(windows, key=lambda item: (item.start_ms, item.end_ms)):
        if not merged or row.start_ms > merged[-1][1] + 1:
            merged.append([int(row.start_ms), int(row.end_ms)])
        else:
            merged[-1][1] = max(merged[-1][1], int(row.end_ms))
    return [(start, end) for start, end in merged]


def _threshold_key(value: float) -> str:
    return format(float(value), "g")


def scan_lead_shock_thresholds(
    root: str | Path,
    sources: Sequence[str | Path],
    *,
    market_windows: Sequence[SourceWindow] | None = None,
    thresholds_bps: Sequence[float] = (4.0, 6.0, 8.0, 10.0, 12.0, 16.0, 20.0),
    coin: str = "ETH",
    window_ms: int = 1_000,
    cooldown_ms: int = 5_000,
    cutoff_ms: int | None = None,
) -> dict[str, Any]:
    """Scan historical lead trades once for a predeclared threshold grid."""

    project_root = Path(root).resolve()
    selected_coin = str(coin).upper()
    thresholds = sorted({float(value) for value in thresholds_bps if float(value) > 0})
    if not thresholds:
        raise ValueError("thresholds_bps must contain at least one positive threshold")
    ranges = _merge_ranges(market_windows or discover_market_tick_windows(project_root))
    range_starts = [start for start, _ in ranges]
    active: deque[tuple[int, float]] = deque()
    last_trigger = {value: -10**18 for value in thresholds}
    stats = {
        value: {
            "shock_count": 0,
            "up_count": 0,
            "down_count": 0,
            "max_abs_shock_bps": 0.0,
            "first_trigger_ms": None,
            "last_trigger_ms": None,
        }
        for value in thresholds
    }
    lines_read = invalid = outside = duplicates = lead_trades = 0
    max_window_points = 0
    first_trade_ms: int | None = None
    last_trade_ms: int | None = None
    last_row_timestamp = -10**18
    identities_at_last_timestamp: set[tuple[Any, ...]] = set()
    consumed: list[str] = []

    for raw_path in sources:
        path = Path(raw_path)
        if not path.is_absolute():
            path = project_root / path
        path = path.resolve()
        if not path.is_file():
            continue
        consumed.append(
            path.relative_to(project_root).as_posix()
            if path.is_relative_to(project_root)
            else str(path)
        )
        for line in _lines(path):
            lines_read += 1
            if "BIN_TRADE" not in line or selected_coin not in line.upper():
                continue
            try:
                record = json.loads(line)
            except (TypeError, ValueError):
                invalid += 1
                continue
            if not isinstance(record, dict):
                invalid += 1
                continue
            if str(record.get("venue") or "") != "BIN_TRADE":
                continue
            if str(record.get("coin") or "").upper() != selected_coin:
                continue
            timestamp_ms = _wall_ms(record)
            price = _finite(record.get("px"))
            if timestamp_ms is None or price is None or price <= 0:
                invalid += 1
                continue
            if cutoff_ms is not None and timestamp_ms > int(cutoff_ms):
                outside += 1
                continue
            range_index = bisect.bisect_right(range_starts, timestamp_ms) - 1
            if range_index < 0 or timestamp_ms > ranges[range_index][1]:
                outside += 1
                continue
            identity = (
                str(record.get("event_id") or ""),
                timestamp_ms,
                float(price),
                str(record.get("side") or "").upper(),
                record.get("sz"),
            )
            if timestamp_ms < last_row_timestamp:
                duplicates += 1
                continue
            if timestamp_ms > last_row_timestamp:
                last_row_timestamp = timestamp_ms
                identities_at_last_timestamp.clear()
            elif identity in identities_at_last_timestamp:
                duplicates += 1
                continue
            identities_at_last_timestamp.add(identity)

            while active and timestamp_ms - active[0][0] > max(1, int(window_ms)):
                active.popleft()
            if active:
                base_price = active[0][1]
                shock_bps = (float(price) - base_price) / base_price * 10_000.0
                absolute = abs(shock_bps)
                for threshold in thresholds:
                    if absolute < threshold:
                        continue
                    if timestamp_ms - last_trigger[threshold] < max(0, int(cooldown_ms)):
                        continue
                    row = stats[threshold]
                    row["shock_count"] += 1
                    row["up_count" if shock_bps > 0 else "down_count"] += 1
                    row["max_abs_shock_bps"] = max(
                        float(row["max_abs_shock_bps"]), absolute
                    )
                    row["first_trigger_ms"] = row["first_trigger_ms"] or timestamp_ms
                    row["last_trigger_ms"] = timestamp_ms
                    last_trigger[threshold] = timestamp_ms
            active.append((timestamp_ms, float(price)))
            max_window_points = max(max_window_points, len(active))
            lead_trades += 1
            first_trade_ms = timestamp_ms if first_trade_ms is None else first_trade_ms
            last_trade_ms = timestamp_ms

    coverage_ms = sum(end - start + 1 for start, end in ranges)
    threshold_rows: dict[str, dict[str, Any]] = {}
    for threshold, row in stats.items():
        count = int(row["shock_count"])
        threshold_rows[_threshold_key(threshold)] = {
            **row,
            "max_abs_shock_bps": round(float(row["max_abs_shock_bps"]), 8),
            "shocks_per_covered_day": (
                round(count * 86_400_000.0 / coverage_ms, 8) if coverage_ms > 0 else None
            ),
        }
    return {
        "schema_version": "hypersmart.lead_lag_streaming_threshold_scan.v1",
        "status": "COMPLETED" if ranges else "NO_MARKET_WINDOWS",
        "coin": selected_coin,
        "window_ms": int(window_ms),
        "cooldown_ms": int(cooldown_ms),
        "cutoff_ms": cutoff_ms,
        "sources_read": len(consumed),
        "sources": consumed,
        "lines_read": lines_read,
        "lead_trades": lead_trades,
        "invalid_rows": invalid,
        "rows_outside_execution_windows": outside,
        "duplicates_rejected": duplicates,
        "first_trade_ms": first_trade_ms,
        "last_trade_ms": last_trade_ms,
        "market_ranges": [list(row) for row in ranges],
        "covered_wall_ms": coverage_ms,
        "max_window_points": max_window_points,
        "thresholds": threshold_rows,
        "memory_policy": "ROLLING_WINDOW_PLUS_SCALAR_COUNTS",
        "paper_read_only": True,
        "real_execution": False,
    }


def _relative(root: Path, path: Path) -> str:
    return path.relative_to(root).as_posix() if path.is_relative_to(root) else str(path)


def immutable_aligned_source_manifest(root: str | Path) -> dict[str, Any]:
    """Fingerprint immutable BBO and market-window inputs for one TRAIN scan."""

    project_root = Path(root).resolve()
    aligned, alignment = select_aligned_bbo_sources(project_root)
    sources = [path.resolve() for path in aligned if path.suffix == ".gz"]
    market_windows = [
        row
        for row in discover_market_tick_windows(project_root)
        if row.path.suffix == ".gz" and row.path.is_file()
    ]
    source_rows = []
    for path in sources:
        stat = path.stat()
        source_rows.append(
            {
                "path": _relative(project_root, path),
                "size": stat.st_size,
                "mtime_ns": stat.st_mtime_ns,
            }
        )
    window_rows = []
    for row in market_windows:
        stat = row.path.stat()
        window_rows.append(
            {
                "path": _relative(project_root, row.path),
                "start_ms": row.start_ms,
                "end_ms": row.end_ms,
                "size": stat.st_size,
                "mtime_ns": stat.st_mtime_ns,
            }
        )
    fingerprint_payload = {
        "schema_version": "hypersmart.lead_lag_streaming_manifest.v1",
        "sources": source_rows,
        "market_windows": window_rows,
    }
    digest = hashlib.sha256(
        json.dumps(fingerprint_payload, sort_keys=True, separators=(",", ":")).encode(
            "utf-8"
        )
    ).hexdigest()
    cutoff_ms = max((row.end_ms for row in market_windows), default=0)
    cutoff_utc = (
        datetime.fromtimestamp(cutoff_ms / 1000.0, tz=UTC)
        .isoformat()
        .replace("+00:00", "Z")
        if cutoff_ms > 0
        else "1970-01-01T00:00:00Z"
    )
    return {
        "schema_version": fingerprint_payload["schema_version"],
        "data_fingerprint": f"sha256:{digest}",
        "data_cutoff_utc": cutoff_utc,
        "cutoff_ms": cutoff_ms,
        "source_count": len(sources),
        "source_bytes": sum(int(row["size"]) for row in source_rows),
        "market_window_count": len(market_windows),
        "alignment": alignment,
        "source_paths": sources,
        "market_windows": market_windows,
    }


def evaluate_streaming_threshold_feasibility(
    params: dict[str, Any],
    *,
    budget: float = 1.0,
    context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Evaluate shock-frequency feasibility without treating it as PnL evidence."""

    del budget
    experiment_context = dict(context or {})
    signature = str(experiment_context.get("signature") or "")
    manifest = immutable_aligned_source_manifest(Path.cwd())
    if manifest["data_fingerprint"] != experiment_context.get("data_fingerprint"):
        raise ValueError("immutable TRAIN source fingerprint differs from experiment spec")
    if manifest["data_cutoff_utc"] != experiment_context.get("data_cutoff_utc"):
        raise ValueError("immutable TRAIN cutoff differs from experiment spec")
    if signature not in _FEASIBILITY_CACHE:
        _FEASIBILITY_CACHE[signature] = scan_lead_shock_thresholds(
            Path.cwd(),
            manifest["source_paths"],
            market_windows=manifest["market_windows"],
            thresholds_bps=THRESHOLD_GRID_BPS,
            cutoff_ms=int(manifest["cutoff_ms"]),
        )
    scan = _FEASIBILITY_CACHE[signature]
    threshold = float(params.get("threshold_bps") or 0.0)
    threshold_row = dict(scan["thresholds"].get(_threshold_key(threshold)) or {})
    return {
        # This experiment measures event availability only.  Zero prevents the
        # generic optimizer from interpreting frequency as an economic edge.
        "net_median_bps": 0.0,
        "candidate_verdict": "ITERATE",
        "diagnostic_only": True,
        "threshold_bps": threshold,
        "shock_count": int(threshold_row.get("shock_count") or 0),
        "shocks_per_covered_day": threshold_row.get("shocks_per_covered_day"),
        "threshold_result": threshold_row,
        "threshold_scan": scan["thresholds"],
        "lines_read": scan["lines_read"],
        "lead_trades": scan["lead_trades"],
        "covered_wall_ms": scan["covered_wall_ms"],
        "max_window_points": scan["max_window_points"],
        "source_count": manifest["source_count"],
        "source_bytes": manifest["source_bytes"],
        "memory_policy": scan["memory_policy"],
        "paper_read_only": True,
        "real_execution": False,
    }


__all__ = [
    "THRESHOLD_GRID_BPS",
    "evaluate_streaming_threshold_feasibility",
    "immutable_aligned_source_manifest",
    "scan_lead_shock_thresholds",
]
