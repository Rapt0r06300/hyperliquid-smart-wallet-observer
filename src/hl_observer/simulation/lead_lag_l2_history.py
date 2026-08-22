"""Bounded historical Hyperliquid L2 loader for strict Lead-Lag economics.

The BBO tape is intentionally small and historically did not persist top sizes.
The canonical tick dataset, however, stores every read-only ``l2Book`` frame
with its receive wall clock and raw payload.  This module recovers that already
recorded execution evidence without opening a second network connection.

Only real recorded observations are accepted.  Missing/corrupt/clockless rows
are skipped and surfaced in metadata; callers must fail closed when coverage is
insufficient.
"""
from __future__ import annotations

import gzip
import json
import math
import re
import time
from collections import defaultdict
from collections.abc import Iterator, Mapping, Sequence
from pathlib import Path
from typing import Any

TICK_DIR = Path("runtime") / "data" / "market_ticks"
STREAM_NAME = "hyperliquid_market_ticks"
DEFAULT_MAX_FILES = 96
DEFAULT_MAX_LINES = 2_000_000
DEFAULT_TIME_BUDGET_S = 30.0
_SHARD_RANGE_RE = re.compile(
    rf"^{re.escape(STREAM_NAME)}\.(\d+)-(\d+)\.\d+\.jsonl\.gz$"
)


def _shard_range_ms(path: Path) -> tuple[int, int] | None:
    """Return the durable shard range encoded by modern collector names."""

    match = _SHARD_RANGE_RE.match(path.name)
    if match is None:
        return None
    start_ms, end_ms = (int(value) for value in match.groups())
    if start_ms < 1_500_000_000_000 or end_ms < start_ms:
        return None
    return start_ms, end_ms


def _overlaps(
    source_range: tuple[int, int] | None,
    *,
    start_ms: int | None,
    end_ms: int | None,
) -> bool:
    if source_range is None or (start_ms is None and end_ms is None):
        return True
    source_start, source_end = source_range
    if start_ms is not None and source_end < int(start_ms):
        return False
    if end_ms is not None and source_start > int(end_ms):
        return False
    return True


def _source_sort_key(path: Path) -> tuple[int, int, int, str, str]:
    source_range = _shard_range_ms(path)
    if source_range is not None:
        return 0, source_range[0], source_range[1], path.name, path.as_posix()
    return 1, 0, 0, path.name, path.as_posix()


def discover_l2_sources(
    root: str | Path,
    *,
    max_files: int = DEFAULT_MAX_FILES,
    start_ms: int | None = None,
    end_ms: int | None = None,
) -> list[Path]:
    directory = Path(root) / TICK_DIR
    current = directory / f"{STREAM_NAME}.current.jsonl"
    current_resolved = current.resolve() if current.is_file() else None

    # Older collectors wrote immutable shards below ``shards/``.  The current
    # collector seals them directly beside the live file.  Economic replay must
    # see both layouts or it silently ignores most of the recorded L2 history.
    shard_candidates = list(directory.glob(f"{STREAM_NAME}.*.jsonl.gz"))
    shards = directory / "shards"
    if shards.is_dir():
        shard_candidates.extend(shards.glob(f"{STREAM_NAME}.*.jsonl.gz"))
    immutable = sorted(
        {
            path.resolve()
            for path in shard_candidates
            if current_resolved is None or path.resolve() != current_resolved
            if _overlaps(_shard_range_ms(path), start_ms=start_ms, end_ms=end_ms)
        },
        key=_source_sort_key,
    )

    if max_files > 0:
        shard_budget = max(0, int(max_files) - (1 if current_resolved else 0))
        immutable = immutable[-shard_budget:] if shard_budget else []
    # With an explicit causal window, immutable shards are already reduced to
    # the overlap and are read chronologically before the live tail. Without a
    # window, preserve the historical live-first bounded behaviour.
    if start_ms is not None or end_ms is not None:
        return [*immutable, *([current_resolved] if current_resolved else [])]
    return [*([current_resolved] if current_resolved else []), *immutable]


def _outside_window(
    record: Mapping[str, Any],
    *,
    start_ms: int | None,
    end_ms: int | None,
) -> bool:
    if start_ms is None and end_ms is None:
        return False
    clocks = _local_timestamps_ms(record)
    if clocks is None:
        return False
    observed_ms = clocks[2]
    return bool(
        (start_ms is not None and observed_ms < int(start_ms))
        or (end_ms is not None and observed_ms > int(end_ms))
    )


def _lines(path: Path) -> Iterator[str]:
    opener = gzip.open if path.suffix == ".gz" else open
    try:
        with opener(path, "rt", encoding="utf-8", errors="ignore") as handle:
            yield from handle
    except OSError:
        return


def _positive(value: object) -> float | None:
    try:
        parsed = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return parsed if math.isfinite(parsed) and parsed > 0 else None


def _local_timestamps_ms(record: Mapping[str, Any]) -> tuple[int, int, int] | None:
    """Return receive, durable-write and causal observable wall clocks.

    A historical replay may only consume a frame once it was durably written.
    Requiring both local clocks also prevents silently falling back to an
    exchange timestamp when a damaged row is encountered.
    """
    received = _positive(record.get("received_ts_ms"))
    if received is None:
        received = _positive(record.get("recv_wall_ts_ms"))
    written = _positive(record.get("written_ts_ms"))
    if written is None:
        written = _positive(record.get("write_wall_ts_ms"))
    if (
        received is None
        or written is None
        or received < 1_500_000_000_000
        or written < 1_500_000_000_000
        or written < received
    ):
        return None
    received_ms = int(received)
    written_ms = int(written)
    return received_ms, written_ms, max(received_ms, written_ms)


def _quality_metadata(record: Mapping[str, Any], coin: str) -> tuple[float | None, bool, list[str]]:
    summary = record.get("parsed_summary")
    if not isinstance(summary, Mapping):
        return None, False, ["MISSING_PARSED_SUMMARY"]
    quality: Mapping[str, Any] = summary
    by_coin = summary.get("quality_by_coin")
    if isinstance(by_coin, Mapping) and isinstance(by_coin.get(coin), Mapping):
        quality = by_coin[coin]
    score_raw = quality.get("feed_quality_score")
    try:
        score = float(score_raw) if score_raw is not None else None
    except (TypeError, ValueError, OverflowError):
        score = None
    reasons_raw = quality.get("quality_reasons", quality.get("reasons", ()))
    if isinstance(reasons_raw, str):
        reasons = [item for item in reasons_raw.split("|") if item]
    elif isinstance(reasons_raw, Sequence):
        reasons = [str(item) for item in reasons_raw if str(item)]
    else:
        reasons = []
    return score, bool(quality.get("data_gate_ready")), reasons


def _raw_message(record: Mapping[str, Any]) -> Mapping[str, Any] | None:
    raw = record.get("raw_payload")
    if isinstance(raw, Mapping):
        return raw
    if not isinstance(raw, str) or not raw.strip():
        return None
    try:
        value = json.loads(raw)
    except (TypeError, ValueError):
        return None
    return value if isinstance(value, Mapping) else None


def _level(row: object) -> tuple[float, float] | None:
    try:
        if isinstance(row, Mapping):
            price = _positive(row.get("px"))
            size = _positive(row.get("sz"))
        elif isinstance(row, Sequence) and not isinstance(row, (str, bytes, bytearray)):
            price = _positive(row[0])
            size = _positive(row[1])
        else:
            return None
    except (IndexError, KeyError, TypeError):
        return None
    if price is None or size is None:
        return None
    return price, size


def snapshot_from_tick(record: Mapping[str, Any]) -> dict[str, Any] | None:
    """Extract one causal, executable top-of-book observation from a tick row."""
    if str(record.get("channel") or "") != "l2Book":
        return None
    if record.get("real_execution") not in {False, None}:
        return None
    local_clocks = _local_timestamps_ms(record)
    if local_clocks is None:
        return None
    received_ts_ms, written_ts_ms, observable_at_ms = local_clocks
    message = _raw_message(record)
    if not message or str(message.get("channel") or "") != "l2Book":
        return None
    data = message.get("data")
    if not isinstance(data, Mapping):
        return None
    levels = data.get("levels")
    if not isinstance(levels, Sequence) or len(levels) < 2:
        return None
    bids = levels[0] if isinstance(levels[0], Sequence) else ()
    asks = levels[1] if isinstance(levels[1], Sequence) else ()
    if not bids or not asks:
        return None
    best_bid = _level(bids[0])
    best_ask = _level(asks[0])
    if best_bid is None or best_ask is None or best_ask[0] < best_bid[0]:
        return None
    coin = str(data.get("coin") or record.get("instrument") or "").strip().upper()
    if not coin:
        return None

    bid_levels = [parsed for raw in bids if (parsed := _level(raw)) is not None]
    ask_levels = [parsed for raw in asks if (parsed := _level(raw)) is not None]
    if not bid_levels or not ask_levels:
        return None
    quality_score, gate_ready, quality_reasons = _quality_metadata(record, coin)
    return {
        "coin": coin,
        "ts_ms": observable_at_ms,
        "received_ts_ms": received_ts_ms,
        "written_ts_ms": written_ts_ms,
        "observable_at_ms": observable_at_ms,
        "exchange_ts_ms": int(float(data.get("time"))) if _positive(data.get("time")) else None,
        "bid": best_bid[0],
        "ask": best_ask[0],
        "bid_size": best_bid[1],
        "ask_size": best_ask[1],
        "bid_top_usd": best_bid[0] * best_bid[1],
        "ask_top_usd": best_ask[0] * best_ask[1],
        "bid_depth_usd": sum(price * size for price, size in bid_levels),
        "ask_depth_usd": sum(price * size for price, size in ask_levels),
        "connection_id": record.get("connection_id"),
        "sequence": record.get("sequence"),
        "reconnect_count": int(record.get("reconnect_count") or 0),
        "gap_count": int(record.get("gap_count") or 0),
        "feed_quality_score": quality_score,
        "data_gate_ready": gate_ready,
        "quality_reasons": quality_reasons,
        "raw_sha256": str(record.get("raw_sha256") or ""),
        "source": "hyperliquid:recorded:l2Book",
        "data_origin": "RECORDED_REAL",
        "read_only": True,
        "real_execution": False,
    }


def public_trades_from_tick(record: Mapping[str, Any]) -> list[dict[str, Any]]:
    """Extract causal public trades from one recorded read-only WS frame."""
    if str(record.get("channel") or "") != "trades":
        return []
    if record.get("real_execution") not in {False, None}:
        return []
    local_clocks = _local_timestamps_ms(record)
    if local_clocks is None:
        return []
    received_ts_ms, written_ts_ms, observable_at_ms = local_clocks
    message = _raw_message(record)
    if not message or str(message.get("channel") or "") != "trades":
        return []
    payload = message.get("data")
    if not isinstance(payload, Sequence) or isinstance(payload, (str, bytes, bytearray)):
        return []

    result: list[dict[str, Any]] = []
    for index, item in enumerate(payload):
        if not isinstance(item, Mapping):
            continue
        coin = str(item.get("coin") or record.get("instrument") or "").strip().upper()
        side = str(item.get("side") or "").strip().upper()
        price = _positive(item.get("px"))
        size = _positive(item.get("sz"))
        if not coin or side not in {"A", "B"} or price is None or size is None:
            continue
        quality_score, gate_ready, quality_reasons = _quality_metadata(record, coin)
        identity = str(item.get("hash") or item.get("tid") or "")
        if not identity:
            identity = f"{record.get('raw_sha256') or ''}:{index}"
        result.append(
            {
                "coin": coin,
                "ts_ms": observable_at_ms,
                "received_ts_ms": received_ts_ms,
                "written_ts_ms": written_ts_ms,
                "observable_at_ms": observable_at_ms,
                "exchange_ts_ms": (
                    int(float(item.get("time"))) if _positive(item.get("time")) else None
                ),
                "side": side,
                "px": price,
                "sz": size,
                "trade_id": identity,
                "feed_quality_score": quality_score,
                "data_gate_ready": gate_ready,
                "quality_reasons": quality_reasons,
                "source": "hyperliquid:recorded:trades",
                "data_origin": "RECORDED_REAL",
                "read_only": True,
                "real_execution": False,
            }
        )
    return result


def load_market_microstructure_history(
    root: str | Path,
    *,
    max_files: int = DEFAULT_MAX_FILES,
    max_lines: int = DEFAULT_MAX_LINES,
    time_budget_s: float = DEFAULT_TIME_BUDGET_S,
    start_ms: int | None = None,
    end_ms: int | None = None,
) -> tuple[
    dict[str, list[dict[str, Any]]],
    dict[str, list[dict[str, Any]]],
    dict[str, Any],
]:
    """Load L2 and public trades in one bounded pass over the real tick store."""
    project_root = Path(root).resolve()
    sources = discover_l2_sources(
        project_root,
        max_files=max_files,
        start_ms=start_ms,
        end_ms=end_ms,
    )
    books: dict[str, list[dict[str, Any]]] = defaultdict(list)
    trades: dict[str, list[dict[str, Any]]] = defaultdict(list)
    seen_books: set[str] = set()
    seen_trades: set[str] = set()
    started = time.monotonic()
    lines_read = invalid = duplicate_books = duplicate_trades = outside_window = 0
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
            if '"l2Book"' not in line and '"trades"' not in line:
                continue
            try:
                record = json.loads(line)
            except (TypeError, ValueError):
                invalid += 1
                continue
            if not isinstance(record, Mapping):
                invalid += 1
                continue
            if _outside_window(record, start_ms=start_ms, end_ms=end_ms):
                outside_window += 1
                continue
            if str(record.get("channel") or "") == "l2Book":
                snapshot = snapshot_from_tick(record)
                if snapshot is None:
                    invalid += 1
                    continue
                identity = str(snapshot.get("raw_sha256") or "") or (
                    f"{snapshot['coin']}|{snapshot['ts_ms']}|{snapshot['bid']}|{snapshot['ask']}"
                )
                if identity in seen_books:
                    duplicate_books += 1
                    continue
                seen_books.add(identity)
                books[str(snapshot["coin"])].append(snapshot)
            elif str(record.get("channel") or "") == "trades":
                parsed = public_trades_from_tick(record)
                if not parsed:
                    invalid += 1
                    continue
                for trade in parsed:
                    identity = str(trade["trade_id"])
                    if identity in seen_trades:
                        duplicate_trades += 1
                        continue
                    seen_trades.add(identity)
                    trades[str(trade["coin"])].append(trade)
        if stopped_reason != "COMPLETED":
            break

    book_result = dict(books)
    trade_result = dict(trades)
    for rows in (*book_result.values(), *trade_result.values()):
        rows.sort(key=lambda row: int(row["ts_ms"]))
    return book_result, trade_result, {
        "schema_version": "hypersmart.lead_lag_microstructure_history.v1",
        "sources": [
            source.relative_to(project_root).as_posix()
            if source.is_relative_to(project_root)
            else str(source)
            for source in sources
        ],
        "sources_read": len(sources),
        "lines_read": lines_read,
        "l2_rows": sum(len(rows) for rows in book_result.values()),
        "trade_rows": sum(len(rows) for rows in trade_result.values()),
        "coins_with_l2": len(book_result),
        "coins_with_trades": len(trade_result),
        "duplicate_l2_rejected": duplicate_books,
        "duplicate_trades_rejected": duplicate_trades,
        "invalid_rows": invalid,
        "rows_outside_window": outside_window,
        "stopped_reason": stopped_reason,
        "requested_start_ms": int(start_ms) if start_ms is not None else None,
        "requested_end_ms": int(end_ms) if end_ms is not None else None,
        "source_time_filter_applied": start_ms is not None or end_ms is not None,
        "clock": "DURABLE_OBSERVABLE_MAX_RECEIVE_WRITE_MS",
        "read_only": True,
        "real_execution": False,
    }


def load_l2_history(
    root: str | Path,
    *,
    max_files: int = DEFAULT_MAX_FILES,
    max_lines: int = DEFAULT_MAX_LINES,
    time_budget_s: float = DEFAULT_TIME_BUDGET_S,
    start_ms: int | None = None,
    end_ms: int | None = None,
) -> tuple[dict[str, list[dict[str, Any]]], dict[str, Any]]:
    """Load recorded L2 rows by coin with explicit bounded-work diagnostics."""
    project_root = Path(root).resolve()
    sources = discover_l2_sources(
        project_root,
        max_files=max_files,
        start_ms=start_ms,
        end_ms=end_ms,
    )
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    seen: set[str] = set()
    started = time.monotonic()
    lines_read = 0
    l2_rows = 0
    duplicates = 0
    invalid = 0
    outside_window = 0
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
            if '"l2Book"' not in line:
                continue
            try:
                record = json.loads(line)
            except (TypeError, ValueError):
                invalid += 1
                continue
            if not isinstance(record, Mapping):
                invalid += 1
                continue
            if _outside_window(record, start_ms=start_ms, end_ms=end_ms):
                outside_window += 1
                continue
            snapshot = snapshot_from_tick(record)
            if snapshot is None:
                invalid += 1
                continue
            identity = str(snapshot.get("raw_sha256") or "")
            if not identity:
                identity = f"{snapshot['coin']}|{snapshot['ts_ms']}|{snapshot['bid']}|{snapshot['ask']}"
            if identity in seen:
                duplicates += 1
                continue
            seen.add(identity)
            grouped[str(snapshot["coin"])].append(snapshot)
            l2_rows += 1
        if stopped_reason != "COMPLETED":
            break

    result = dict(grouped)
    for rows in result.values():
        rows.sort(key=lambda row: int(row["ts_ms"]))
    return result, {
        "schema_version": "hypersmart.lead_lag_l2_history.v2",
        "sources": [
            source.relative_to(project_root).as_posix()
            if source.is_relative_to(project_root)
            else str(source)
            for source in sources
        ],
        "sources_read": len(sources),
        "lines_read": lines_read,
        "l2_rows": l2_rows,
        "coins": len(result),
        "duplicates_rejected": duplicates,
        "invalid_rows": invalid,
        "rows_outside_window": outside_window,
        "stopped_reason": stopped_reason,
        "requested_start_ms": int(start_ms) if start_ms is not None else None,
        "requested_end_ms": int(end_ms) if end_ms is not None else None,
        "source_time_filter_applied": start_ms is not None or end_ms is not None,
        "clock": "DURABLE_OBSERVABLE_MAX_RECEIVE_WRITE_MS",
        "read_only": True,
        "real_execution": False,
    }


__all__ = [
    "discover_l2_sources",
    "load_l2_history",
    "load_market_microstructure_history",
    "public_trades_from_tick",
    "snapshot_from_tick",
]
