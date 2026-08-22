"""Causal source alignment for the Lead-Lag queue replay.

Binance lead trades and Hyperliquid execution evidence are recorded in
different shard families.  Selecting the newest files independently can join
disjoint wall-clock periods and make every otherwise valid shock unexecutable.
This module selects only BBO shards that overlap recorded Hyperliquid market
tick windows and streams the narrow ETH lead tape needed by the V3 replay.

Local PAPER/READ-ONLY research only.  No network and no execution surface.
"""
from __future__ import annotations

import bisect
import gzip
import json
import math
import re
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterator, Sequence

MARKET_STREAM = "hyperliquid_market_ticks"
_MARKET_RANGE_RE = re.compile(
    rf"^{re.escape(MARKET_STREAM)}\.(\d+)-(\d+)\.\d+\.jsonl\.gz$"
)
_BBO_END_RE = re.compile(r"^bbo_tape_(\d+)\.jsonl(?:\.gz)?$")
_MIN_WALL_MS = 1_500_000_000_000


@dataclass(frozen=True)
class SourceWindow:
    path: Path
    start_ms: int
    end_ms: int


def _lines(path: Path) -> Iterator[str]:
    opener = gzip.open if path.suffix == ".gz" else open
    try:
        with opener(path, "rt", encoding="utf-8", errors="ignore") as handle:
            yield from handle
    except OSError:
        return


def _finite(value: object) -> float | None:
    try:
        parsed = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return parsed if math.isfinite(parsed) else None


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
        if value is not None and value >= _MIN_WALL_MS:
            return int(value)
    collected = _finite(record.get("collecte_ts"))
    if collected is not None and collected >= _MIN_WALL_MS / 1000:
        return int(collected * 1000.0)
    return None


def _first_wall_ms(path: Path, *, max_lines: int = 256) -> int | None:
    for index, line in enumerate(_lines(path)):
        if index >= max(1, int(max_lines)):
            break
        try:
            record = json.loads(line)
        except (TypeError, ValueError):
            continue
        if isinstance(record, dict):
            value = _wall_ms(record)
            if value is not None:
                return value
    return None


def _bbo_filename_end_ms(path: Path) -> int | None:
    match = _BBO_END_RE.match(path.name)
    if match is None:
        return None
    raw = int(match.group(1))
    if raw >= _MIN_WALL_MS * 100_000:
        return raw // 1_000_000
    if raw >= _MIN_WALL_MS:
        return raw
    return None


def _market_filename_window(path: Path) -> SourceWindow | None:
    match = _MARKET_RANGE_RE.match(path.name)
    if match is None:
        return None
    start_ms, end_ms = (int(value) for value in match.groups())
    if start_ms < _MIN_WALL_MS or end_ms < start_ms:
        return None
    return SourceWindow(path.resolve(), start_ms, end_ms)


def _current_window(path: Path) -> SourceWindow | None:
    start_ms = _first_wall_ms(path)
    if start_ms is None:
        return None
    end_ms = max(start_ms, int(path.stat().st_mtime_ns // 1_000_000))
    return SourceWindow(path.resolve(), start_ms, end_ms)


def discover_market_tick_windows(root: str | Path) -> list[SourceWindow]:
    directory = Path(root).resolve() / "runtime" / "data" / "market_ticks"
    candidates = list(directory.glob(f"{MARKET_STREAM}.*.jsonl.gz"))
    legacy = directory / "shards"
    if legacy.is_dir():
        candidates.extend(legacy.glob(f"{MARKET_STREAM}.*.jsonl.gz"))
    windows = [
        window
        for path in sorted({item.resolve() for item in candidates})
        if (window := _market_filename_window(path)) is not None
    ]
    current = directory / f"{MARKET_STREAM}.current.jsonl"
    if current.is_file() and (window := _current_window(current)) is not None:
        windows.append(window)
    return sorted(windows, key=lambda item: (item.start_ms, item.end_ms, item.path.as_posix()))


def _merge_ranges(windows: Sequence[SourceWindow]) -> list[tuple[int, int]]:
    merged: list[list[int]] = []
    for window in sorted(windows, key=lambda item: (item.start_ms, item.end_ms)):
        if not merged or window.start_ms > merged[-1][1] + 1:
            merged.append([window.start_ms, window.end_ms])
        else:
            merged[-1][1] = max(merged[-1][1], window.end_ms)
    return [(start, end) for start, end in merged]


def _overlaps_any(start_ms: int, end_ms: int, ranges: Sequence[tuple[int, int]]) -> bool:
    starts = [item[0] for item in ranges]
    index = bisect.bisect_right(starts, end_ms) - 1
    return index >= 0 and ranges[index][1] >= start_ms


def _candidate_bbo_sources(root: Path) -> list[Path]:
    data = root / "runtime" / "data"
    candidates: list[Path] = []
    for path in (data / "bbo_tape.jsonl.prev", data / "bbo_tape.jsonl"):
        if path.is_file():
            candidates.append(path.resolve())
    for directory in (data / "bbo_shards_archive", data / "bbo_shards"):
        if directory.is_dir():
            candidates.extend(path.resolve() for path in directory.glob("bbo_tape_*.jsonl*"))
    return sorted(set(candidates), key=lambda path: path.as_posix())


def select_aligned_bbo_sources(
    root: str | Path,
    *,
    candidates: Sequence[str | Path] | None = None,
) -> tuple[list[Path], dict[str, Any]]:
    """Select every recorded Binance/BBO source overlapping market truth."""

    project_root = Path(root).resolve()
    market_windows = discover_market_tick_windows(project_root)
    market_ranges = _merge_ranges(market_windows)
    raw_candidates = (
        _candidate_bbo_sources(project_root)
        if candidates is None
        else [
            (Path(value) if Path(value).is_absolute() else project_root / Path(value)).resolve()
            for value in candidates
        ]
    )
    source_windows: list[SourceWindow] = []
    invalid_windows = 0
    for path in sorted(set(raw_candidates), key=lambda item: item.as_posix()):
        if not path.is_file():
            continue
        start_ms = _first_wall_ms(path)
        if start_ms is None:
            invalid_windows += 1
            continue
        filename_end = _bbo_filename_end_ms(path)
        end_ms = max(
            start_ms,
            filename_end if filename_end is not None else int(path.stat().st_mtime_ns // 1_000_000),
        )
        source_windows.append(SourceWindow(path, start_ms, end_ms))

    aligned_windows = [
        window
        for window in source_windows
        if _overlaps_any(window.start_ms, window.end_ms, market_ranges)
    ]
    aligned_windows.sort(key=lambda item: (item.start_ms, item.end_ms, item.path.as_posix()))
    selected = [window.path for window in aligned_windows]

    def relative(path: Path) -> str:
        return path.relative_to(project_root).as_posix() if path.is_relative_to(project_root) else str(path)

    return selected, {
        "schema_version": "hypersmart.lead_lag_source_alignment.v1",
        "selection_policy": "BBO_WALL_WINDOW_INTERSECTS_RECORDED_HYPERLIQUID_MARKET_TICKS",
        "candidate_sources": len(source_windows),
        "selected_sources": len(selected),
        "invalid_source_windows": invalid_windows,
        "market_tick_windows": len(market_windows),
        "merged_market_ranges": [list(item) for item in market_ranges],
        "selected_bytes": sum(path.stat().st_size for path in selected),
        "sources": [relative(path) for path in selected],
        "paper_read_only": True,
        "real_execution": False,
    }


def load_aligned_binance_trade_tape(
    root: str | Path,
    sources: Sequence[str | Path],
    *,
    coin: str = "ETH",
    market_windows: Sequence[SourceWindow] | None = None,
    max_lines: int = 0,
    time_budget_s: float = 0.0,
) -> tuple[dict[str, dict[str, list]], dict[str, Any]]:
    """Stream only lead trades observable during recorded execution windows."""

    project_root = Path(root).resolve()
    selected_coin = str(coin).upper()
    windows = list(market_windows or discover_market_tick_windows(project_root))
    ranges = _merge_ranges(windows)
    range_starts = [item[0] for item in ranges]
    trades: list[tuple[int, float, float]] = []
    seen: set[tuple[Any, ...]] = set()
    lines_read = invalid = outside_window = duplicates = 0
    consumed: list[str] = []
    started = time.monotonic()
    stopped_reason = "COMPLETED" if ranges else "NO_MARKET_WINDOWS"

    if ranges:
        for value in sources:
            path = Path(value)
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
                if max_lines > 0 and lines_read > int(max_lines):
                    stopped_reason = "MAX_LINES_REACHED"
                    break
                if time_budget_s > 0 and lines_read % 10_000 == 0:
                    if time.monotonic() - started >= float(time_budget_s):
                        stopped_reason = "TIME_BUDGET_REACHED"
                        break
                if "BIN_TRADE" not in line:
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
                range_index = bisect.bisect_right(range_starts, timestamp_ms) - 1
                if range_index < 0 or timestamp_ms > ranges[range_index][1]:
                    outside_window += 1
                    continue
                side = str(record.get("side") or "").upper()
                direction = 1.0 if side == "BUY" else -1.0
                identity = (
                    str(record.get("event_id") or ""),
                    timestamp_ms,
                    float(price),
                    direction,
                    record.get("sz"),
                )
                if identity in seen:
                    duplicates += 1
                    continue
                seen.add(identity)
                trades.append((int(timestamp_ms) * 1_000_000, float(price), direction))
            if stopped_reason != "COMPLETED":
                break

    trades.sort()
    tape = {selected_coin: {"HL": [], "BIN": [], "TRADE": trades}}
    return tape, {
        "schema_version": "hypersmart.aligned_binance_lead_tape.v1",
        "coin": selected_coin,
        "sources_read": len(consumed),
        "sources": consumed,
        "lines_read": lines_read,
        "lead_trades": len(trades),
        "duplicates_rejected": duplicates,
        "invalid_rows": invalid,
        "rows_outside_execution_windows": outside_window,
        "market_ranges": [list(item) for item in ranges],
        "stopped_reason": stopped_reason,
        "clock": "RECORDED_WALL_MS_NORMALIZED_TO_NS",
        "paper_read_only": True,
        "real_execution": False,
    }


__all__ = [
    "SourceWindow",
    "discover_market_tick_windows",
    "load_aligned_binance_trade_tape",
    "select_aligned_bbo_sources",
]
