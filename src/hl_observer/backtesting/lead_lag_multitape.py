"""Bounded, wall-clock-safe loader for Lead-Lag BBO/TRADE history.

The live collector seals ``bbo_tape.jsonl`` into immutable gzip shards. Each
modern record carries ``ts_wall_ms`` in addition to the process-local monotonic
clock. Monotonic clocks from different processes/sessions MUST NOT be merged.
This loader therefore uses wall-clock timestamps when several files are read,
deduplicates overlapping records, and skips cross-session records that cannot
be placed on a common clock.

Read-only. No network and no execution surface.
"""
from __future__ import annotations

import gzip
import hashlib
import json
import os
import time
from pathlib import Path
from typing import Any, Iterator

DEFAULT_MAX_FILES = 96
DEFAULT_MAX_LINES = 2_000_000
DEFAULT_TIME_BUDGET_S = 45.0


def discover_sources(root: str | Path, *, max_files: int = DEFAULT_MAX_FILES) -> list[Path]:
    data = Path(root) / "runtime" / "data"
    candidates: list[Path] = []
    for path in (
        data / "bbo_tape.jsonl.prev",
        data / "bbo_tape.jsonl",
    ):
        if path.is_file():
            candidates.append(path)
    for directory in (data / "bbo_shards_archive", data / "bbo_shards"):
        if directory.is_dir():
            candidates.extend(directory.glob("bbo_tape_*.jsonl"))
            candidates.extend(directory.glob("bbo_tape_*.jsonl.gz"))
    # Deterministic order; all events are sorted by the common wall clock later.
    unique = sorted({path.resolve() for path in candidates}, key=lambda p: p.as_posix())
    if max_files > 0 and len(unique) > max_files:
        # Keep the most recent tail by filename. Shards are timestamp-named.
        unique = unique[-max_files:]
    return unique


def _lines(path: Path) -> Iterator[str]:
    opener = gzip.open if path.suffix == ".gz" else open
    try:
        with opener(path, "rt", encoding="utf-8", errors="ignore") as handle:
            yield from handle
    except OSError:
        return


def _float(value: object) -> float | None:
    try:
        result = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return result if result == result else None


def _wall_ms(record: dict[str, Any]) -> int | None:
    for key in ("ts_wall_ms", "recv_wall_ts_ms", "received_ts_ms", "snapshot_wall_ts_ms"):
        value = _float(record.get(key))
        if value is not None and value >= 1_500_000_000_000:
            return int(value)
    # Generic ``collecte_ts`` is seconds in collecte_fiable.
    value = _float(record.get("collecte_ts"))
    if value is not None and value >= 1_500_000_000:
        return int(value * 1000.0)
    return None


def _identity(record: dict[str, Any], wall_ms: int) -> str:
    fields = (
        str(record.get("venue") or ""),
        str(record.get("coin") or "").upper(),
        str(wall_ms),
        str(record.get("bid") or ""),
        str(record.get("ask") or ""),
        str(record.get("mid") or ""),
        str(record.get("px") or ""),
        str(record.get("side") or ""),
        str(record.get("update_id") or ""),
    )
    return hashlib.sha1("\x1f".join(fields).encode("utf-8", "replace")).hexdigest()


def load_multitape(
    root: str | Path,
    *,
    max_files: int = DEFAULT_MAX_FILES,
    max_lines: int = DEFAULT_MAX_LINES,
    time_budget_s: float = DEFAULT_TIME_BUDGET_S,
) -> tuple[dict[str, dict[str, list]], dict[str, Any]]:
    """Load modern sealed/live tapes into the legacy Lead-Lag shape.

    Returned timestamps are nanoseconds derived from wall milliseconds so the
    existing pure Lead-Lag math can keep its API without cross-session clock
    corruption. Records without a trustworthy wall clock are skipped whenever
    several files are in play. With exactly one source, legacy ``recu_ns`` is
    accepted because no cross-session merge occurs.
    """
    from collections import defaultdict

    sources = discover_sources(root, max_files=max_files)
    multi_source = len(sources) > 1
    per: dict[str, dict[str, list]] = defaultdict(lambda: {"HL": [], "BIN": [], "TRADE": []})
    seen: set[str] = set()
    started = time.monotonic()
    lines_read = 0
    parsed = 0
    duplicates = 0
    missing_wall = 0
    stopped_reason = "COMPLETED"

    for source in sources:
        for line in _lines(source):
            lines_read += 1
            if max_lines > 0 and lines_read > max_lines:
                stopped_reason = "MAX_LINES_REACHED"
                break
            if time_budget_s > 0 and lines_read % 10_000 == 0:
                if time.monotonic() - started >= time_budget_s:
                    stopped_reason = "TIME_BUDGET_REACHED"
                    break
            if not line or '"venue"' not in line:
                continue
            try:
                record = json.loads(line)
            except (TypeError, ValueError):
                continue
            if not isinstance(record, dict):
                continue
            venue = str(record.get("venue") or "")
            coin = str(record.get("coin") or "").upper()
            if not coin or venue not in {"HL", "BIN", "BIN_TRADE"}:
                continue

            wall = _wall_ms(record)
            if wall is None:
                if multi_source:
                    missing_wall += 1
                    continue
                mono = _float(record.get("recu_ns"))
                if mono is None:
                    missing_wall += 1
                    continue
                ts_ns = int(mono)
                # Identity remains source-local in this legacy single-file case.
                wall_for_identity = ts_ns // 1_000_000
            else:
                ts_ns = int(wall) * 1_000_000
                wall_for_identity = int(wall)

            identity = _identity(record, wall_for_identity)
            if identity in seen:
                duplicates += 1
                continue
            seen.add(identity)

            if venue == "HL":
                mid = _float(record.get("mid"))
                bid = _float(record.get("bid"))
                ask = _float(record.get("ask"))
                if mid is None and bid and ask:
                    mid = 0.5 * (bid + ask)
                if mid and mid > 0:
                    per[coin]["HL"].append((ts_ns, mid, bid or mid, ask or mid))
                    parsed += 1
            elif venue == "BIN":
                mid = _float(record.get("mid"))
                if mid and mid > 0:
                    per[coin]["BIN"].append((ts_ns, mid))
                    parsed += 1
            else:
                px = _float(record.get("px"))
                if px and px > 0:
                    side = 1.0 if str(record.get("side") or "").upper() == "BUY" else -1.0
                    per[coin]["TRADE"].append((ts_ns, px, side))
                    parsed += 1
        if stopped_reason != "COMPLETED":
            break

    result = dict(per)
    for coin in result:
        for key in result[coin]:
            result[coin][key].sort()
    meta = {
        "schema_version": "hypersmart.lead_lag_multitape.v1",
        "sources": [path.relative_to(Path(root).resolve()).as_posix() if path.is_relative_to(Path(root).resolve()) else str(path) for path in sources],
        "sources_read": len(sources),
        "lines_read": lines_read,
        "events_parsed": parsed,
        "duplicates_rejected": duplicates,
        "records_without_common_wall_clock": missing_wall,
        "stopped_reason": stopped_reason,
        "clock": "WALL_MS_NORMALIZED_TO_NS" if multi_source else "WALL_OR_SINGLE_SESSION_MONOTONIC",
        "read_only": True,
        "real_execution": False,
    }
    return result, meta


__all__ = ["discover_sources", "load_multitape"]
