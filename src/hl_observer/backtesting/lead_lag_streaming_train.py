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
from statistics import median
from typing import Any

from hl_observer.backtesting.economic_hypotheses_v3 import (
    qualify_lead_lag_queue_maker_train_only,
)
from hl_observer.backtesting.lead_lag_maker_queue_train import (
    load_train_microstructure_history,
)
from hl_observer.backtesting.lead_lag_queue_replay import replay_lead_lag_queue_maker
from hl_observer.backtesting.lead_lag_source_alignment import (
    SourceWindow,
    discover_market_tick_windows,
    select_aligned_bbo_sources,
)
from hl_observer.simulation.lead_lag_measured_replay import (
    load_runtime_latency_evidence,
)

THRESHOLD_GRID_BPS = (4.0, 6.0, 8.0, 10.0, 12.0, 16.0, 20.0)
_FEASIBILITY_CACHE: dict[str, dict[str, Any]] = {}
_MAKER_REPLAY_CACHE: dict[str, dict[str, Any]] = {}


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
            "events": [],
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
                    row["events"].append(
                        {
                            "trigger_ts_ms": int(timestamp_ms),
                            "window_start_ts_ms": int(active[0][0]),
                            "lead_start_price": float(base_price),
                            "lead_trigger_price": float(price),
                            "lead_shock_bps": float(shock_bps),
                            "direction": 1 if shock_bps > 0 else -1,
                        }
                    )
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


def _manifest_fingerprint(
    source_rows: Sequence[dict[str, Any]],
    window_rows: Sequence[dict[str, Any]],
) -> str:
    payload = {
        "schema_version": "hypersmart.lead_lag_streaming_manifest.v1",
        "sources": list(source_rows),
        "market_windows": list(window_rows),
    }
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


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
    schema_version = "hypersmart.lead_lag_streaming_manifest.v1"
    digest = _manifest_fingerprint(source_rows, window_rows)
    cutoff_ms = max((row.end_ms for row in market_windows), default=0)
    cutoff_utc = (
        datetime.fromtimestamp(cutoff_ms / 1000.0, tz=UTC)
        .isoformat()
        .replace("+00:00", "Z")
        if cutoff_ms > 0
        else "1970-01-01T00:00:00Z"
    )
    return {
        "schema_version": schema_version,
        "data_fingerprint": f"sha256:{digest}",
        "data_cutoff_utc": cutoff_utc,
        "cutoff_ms": cutoff_ms,
        "source_count": len(sources),
        "source_bytes": sum(int(row["size"]) for row in source_rows),
        "market_window_count": len(market_windows),
        "alignment": alignment,
        "source_records": source_rows,
        "market_window_records": window_rows,
        "source_paths": sources,
        "market_windows": market_windows,
    }


def write_immutable_source_manifest(
    root: str | Path, target: str | Path
) -> dict[str, Any]:
    """Persist the exact immutable inputs before the experiment starts."""

    project_root = Path(root).resolve()
    manifest = immutable_aligned_source_manifest(project_root)
    source_rows = list(manifest["source_records"])
    window_rows = list(manifest["market_window_records"])
    data_fingerprint = f"sha256:{_manifest_fingerprint(source_rows, window_rows)}"
    payload = {
        "schema_version": "hypersmart.lead_lag_streaming_manifest.v1",
        "data_fingerprint": data_fingerprint,
        "data_cutoff_utc": manifest["data_cutoff_utc"],
        "cutoff_ms": manifest["cutoff_ms"],
        "sources": source_rows,
        "market_windows": window_rows,
        "paper_read_only": True,
        "real_execution": False,
    }
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    manifest_sha256 = hashlib.sha256(canonical).hexdigest()
    path = Path(target)
    if not path.is_absolute():
        path = project_root / path
    path = path.resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)
    return {
        "path": path,
        "manifest_sha256": manifest_sha256,
        "data_fingerprint": data_fingerprint,
        "data_cutoff_utc": manifest["data_cutoff_utc"],
        "source_count": len(source_rows),
        "source_bytes": sum(int(row["size"]) for row in source_rows),
    }


def load_pinned_source_manifest(
    root: str | Path,
    manifest_path: str | Path,
    *,
    expected_manifest_sha256: str,
) -> dict[str, Any]:
    """Load and verify the exact immutable manifest named by an experiment spec."""

    project_root = Path(root).resolve()
    path = Path(manifest_path)
    if not path.is_absolute():
        path = project_root / path
    path = path.resolve()
    if not path.is_relative_to(project_root):
        raise ValueError("pinned TRAIN manifest must stay inside the project root")
    payload = json.loads(path.read_text(encoding="utf-8"))
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    actual_manifest_sha256 = hashlib.sha256(canonical).hexdigest()
    if actual_manifest_sha256 != str(expected_manifest_sha256):
        raise ValueError("pinned TRAIN manifest hash mismatch")
    source_rows = list(payload.get("sources") or [])
    window_rows = list(payload.get("market_windows") or [])
    expected_fingerprint = f"sha256:{_manifest_fingerprint(source_rows, window_rows)}"
    if payload.get("data_fingerprint") != expected_fingerprint:
        raise ValueError("pinned TRAIN data fingerprint mismatch")

    def checked_path(row: dict[str, Any]) -> Path:
        candidate = Path(str(row.get("path") or ""))
        if not candidate.is_absolute():
            candidate = project_root / candidate
        candidate = candidate.resolve()
        if not candidate.is_file():
            relocation_roots = (
                project_root / "runtime" / "data" / "bbo_shards_archive",
                project_root / "runtime" / "data" / "bbo_shards",
                project_root / "runtime" / "data" / "market_ticks",
                project_root / "runtime" / "data" / "market_ticks" / "shards",
            )
            relocated = [
                (directory / candidate.name).resolve()
                for directory in relocation_roots
                if (directory / candidate.name).is_file()
            ]
            matching = [
                path
                for path in relocated
                if path.stat().st_size == int(row.get("size") or -1)
                and path.stat().st_mtime_ns == int(row.get("mtime_ns") or -1)
            ]
            if not matching:
                raise ValueError(f"pinned TRAIN source missing after archive lookup: {candidate}")
            candidate = matching[0]
        stat = candidate.stat()
        if stat.st_size != int(row.get("size") or -1):
            raise ValueError(f"pinned TRAIN source size changed: {candidate}")
        if stat.st_mtime_ns != int(row.get("mtime_ns") or -1):
            raise ValueError(f"pinned TRAIN source mtime changed: {candidate}")
        return candidate

    source_paths = [checked_path(row) for row in source_rows]
    market_windows = [
        SourceWindow(
            checked_path(row),
            int(row["start_ms"]),
            int(row["end_ms"]),
        )
        for row in window_rows
    ]
    return {
        "schema_version": payload.get("schema_version"),
        "data_fingerprint": expected_fingerprint,
        "data_cutoff_utc": str(payload.get("data_cutoff_utc") or ""),
        "cutoff_ms": int(payload.get("cutoff_ms") or 0),
        "source_count": len(source_paths),
        "source_bytes": sum(int(row["size"]) for row in source_rows),
        "market_window_count": len(market_windows),
        "source_paths": source_paths,
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
    if signature not in _FEASIBILITY_CACHE:
        manifest = _manifest_from_context(Path.cwd(), experiment_context)
        if manifest["data_fingerprint"] != experiment_context.get("data_fingerprint"):
            raise ValueError("immutable TRAIN source fingerprint differs from experiment spec")
        if manifest["data_cutoff_utc"] != experiment_context.get("data_cutoff_utc"):
            raise ValueError("immutable TRAIN cutoff differs from experiment spec")
        scan = scan_lead_shock_thresholds(
            Path.cwd(),
            manifest["source_paths"],
            market_windows=manifest["market_windows"],
            thresholds_bps=THRESHOLD_GRID_BPS,
            cutoff_ms=int(manifest["cutoff_ms"]),
        )
        _FEASIBILITY_CACHE[signature] = {"manifest": manifest, "scan": scan}
    cached = _FEASIBILITY_CACHE[signature]
    manifest = cached["manifest"]
    scan = cached["scan"]
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


def _manifest_from_context(root: Path, context: dict[str, Any]) -> dict[str, Any]:
    split_config = dict(context.get("split_config") or {})
    pinned_path = split_config.get("pinned_manifest_path")
    if pinned_path:
        return load_pinned_source_manifest(
            root,
            str(pinned_path),
            expected_manifest_sha256=str(
                split_config.get("pinned_manifest_sha256") or ""
            ),
        )
    return immutable_aligned_source_manifest(root)


def _compact_thresholds(scan: dict[str, Any]) -> dict[str, Any]:
    return {
        str(key): {name: value for name, value in dict(row).items() if name != "events"}
        for key, row in dict(scan.get("thresholds") or {}).items()
    }


def _write_maker_detail(
    root: Path,
    context: dict[str, Any],
    threshold: float,
    payload: dict[str, Any],
) -> tuple[Path, str]:
    experiment_id = str(context.get("experiment_id") or "lead-lag-maker")
    target = (
        root
        / "runtime"
        / "codex_experiments"
        / experiment_id
        / f"MAKER_REPLAY_{_threshold_key(threshold)}BPS.json"
    )
    target.parent.mkdir(parents=True, exist_ok=True)
    canonical = json.dumps(
        payload, sort_keys=True, separators=(",", ":"), default=str
    ).encode("utf-8")
    digest = hashlib.sha256(canonical).hexdigest()
    temporary = target.with_suffix(target.suffix + ".tmp")
    temporary.write_text(
        json.dumps(payload, indent=2, default=str) + "\n", encoding="utf-8"
    )
    temporary.replace(target)
    return target.resolve(), digest


def evaluate_streaming_maker_replay(
    params: dict[str, Any],
    *,
    budget: float = 1.0,
    context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Replay queue-proven TRAIN maker fills for a predeclared shock grid."""

    del budget
    root = Path.cwd()
    experiment_context = dict(context or {})
    signature = str(experiment_context.get("signature") or "")
    if signature not in _MAKER_REPLAY_CACHE:
        manifest = _manifest_from_context(root, experiment_context)
        if manifest["data_fingerprint"] != experiment_context.get("data_fingerprint"):
            raise ValueError("immutable TRAIN source fingerprint differs from experiment spec")
        if manifest["data_cutoff_utc"] != experiment_context.get("data_cutoff_utc"):
            raise ValueError("immutable TRAIN cutoff differs from experiment spec")
        scan = scan_lead_shock_thresholds(
            root,
            manifest["source_paths"],
            market_windows=manifest["market_windows"],
            thresholds_bps=THRESHOLD_GRID_BPS,
            cutoff_ms=int(manifest["cutoff_ms"]),
        )
        minimum_events = list(scan["thresholds"][_threshold_key(6.0)]["events"])
        train_ranges = _merge_ranges(manifest["market_windows"])
        books, public_trades, microstructure = load_train_microstructure_history(
            root,
            [int(row["trigger_ts_ms"]) for row in minimum_events],
            train_ranges=train_ranges,
        )
        _MAKER_REPLAY_CACHE[signature] = {
            "manifest": manifest,
            "scan": scan,
            "train_ranges": train_ranges,
            "books": books,
            "public_trades": public_trades,
            "microstructure": microstructure,
            "latency": load_runtime_latency_evidence(root),
        }
    cached = _MAKER_REPLAY_CACHE[signature]
    manifest = cached["manifest"]
    scan = cached["scan"]
    threshold = float(params.get("threshold_bps") or 0.0)
    threshold_row = dict(scan["thresholds"].get(_threshold_key(threshold)) or {})
    events = list(threshold_row.get("events") or [])
    train_ranges = list(cached["train_ranges"])
    segment_bounds = {
        "train": (
            min((start for start, _ in train_ranges), default=None),
            max((end for _, end in train_ranges), default=None),
        ),
        "validation": (None, None),
        "oos": (None, None),
        "forward": (None, None),
    }
    replay = replay_lead_lag_queue_maker(
        {"ETH": {"TRADE": []}},
        cached["books"],
        cached["public_trades"],
        latency_evidence=cached["latency"],
        shock_threshold_bps=threshold,
        segment_bounds=segment_bounds,
        precomputed_shocks=events,
    )
    qualification = qualify_lead_lag_queue_maker_train_only(
        {
            "maker_queue_candidates": replay["maker_queue_candidates"],
            "maker_queue_replay": replay,
        },
        minimum_abs_shock_bps=threshold,
    )
    rows = list(replay.get("maker_queue_candidates") or [])
    per_trade_net_bps = [
        float(row.get("net_pnl_usd") or 0.0)
        / float(row.get("notional_usd") or 1.0)
        * 10_000.0
        for row in rows
        if float(row.get("notional_usd") or 0.0) > 0
    ]
    nets = [float(row.get("net_pnl_usd") or 0.0) for row in rows]
    total_notional = sum(float(row.get("notional_usd") or 0.0) for row in rows)
    total_cost = sum(
        sum(
            float(row.get(name) or 0.0)
            for name in (
                "fees_usd",
                "spread_cost_usd",
                "slippage_cost_usd",
                "latency_cost_usd",
            )
        )
        for row in rows
    )
    cumulative = peak = maximum_drawdown = 0.0
    for value in nets:
        cumulative += value
        peak = max(peak, cumulative)
        maximum_drawdown = max(maximum_drawdown, peak - cumulative)
    summary = dict((replay.get("segment_summaries") or {}).get("train") or {})
    raw_pf = summary.get("profit_factor")
    finite_pf = float(raw_pf) if isinstance(raw_pf, (int, float)) and math.isfinite(raw_pf) else None
    detail = {
        "schema_version": "hypersmart.lead_lag_streaming_maker_train.v1",
        "base_sha": experiment_context.get("base_sha"),
        "data_fingerprint": experiment_context.get("data_fingerprint"),
        "data_cutoff_utc": experiment_context.get("data_cutoff_utc"),
        "threshold_bps": threshold,
        "shock_events": events,
        "replay": replay,
        "qualification": qualification,
        "microstructure": cached["microstructure"],
        "latency": cached["latency"],
        "paper_read_only": True,
        "real_execution": False,
    }
    detail_path, detail_sha256 = _write_maker_detail(
        root, experiment_context, threshold, detail
    )
    eligible = qualification.get("selection_eligible") is True
    return {
        "net_median_bps": round(median(per_trade_net_bps), 8)
        if per_trade_net_bps
        else 0.0,
        "roi_immobilise_pct": round(sum(nets) / total_notional * 100.0, 8)
        if total_notional > 0
        else 0.0,
        "pf": finite_pf,
        "profit_factor_infinite": raw_pf == float("inf"),
        "drawdown_bps": round(maximum_drawdown / total_notional * 10_000.0, 8)
        if total_notional > 0
        else 0.0,
        "cout_bps": round(total_cost / total_notional * 10_000.0, 8)
        if total_notional > 0
        else 0.0,
        "regularite": sum(value > 0 for value in nets) / len(nets) if nets else 0.0,
        "candidate_verdict": "FREEZE_CANDIDATE" if eligible else "ITERATE",
        "threshold_bps": threshold,
        "shock_count": len(events),
        "queue_proven_fills": int(qualification.get("queue_proven_fills") or 0),
        "train_net_pnl_usd": round(sum(nets), 8),
        "qualification_status": qualification.get("status"),
        "selection_evidence_sha256": qualification.get("selection_evidence_sha256"),
        "diagnostics": replay.get("diagnostics"),
        "threshold_scan": _compact_thresholds(scan),
        "source_time_filter_verified": cached["microstructure"].get(
            "source_time_filter_verified"
        ),
        "detail_artifact": str(detail_path),
        "detail_sha256": detail_sha256,
        "source_count": manifest["source_count"],
        "source_bytes": manifest["source_bytes"],
        "paper_read_only": True,
        "real_execution": False,
    }


__all__ = [
    "THRESHOLD_GRID_BPS",
    "evaluate_streaming_maker_replay",
    "evaluate_streaming_threshold_feasibility",
    "immutable_aligned_source_manifest",
    "load_pinned_source_manifest",
    "scan_lead_shock_thresholds",
    "write_immutable_source_manifest",
]
