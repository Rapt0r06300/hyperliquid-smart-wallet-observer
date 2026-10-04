#!/usr/bin/env python3
"""Collect bounded official public archives into dataset V2."""
from __future__ import annotations

import argparse
import json
from datetime import date
from pathlib import Path

from hl_observer.collection.partitioned_tick_dataset import PartitionedTickDatasetWriter
from hl_observer.data_sources.official_archive_backfill import (
    ArchiveObservationStats,
    fetch_official_archive_stream,
    iter_days,
)
from hl_observer.datasets.v2_pipeline import build_bundle


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--venue", choices=("binance", "bybit", "okx"), required=True)
    parser.add_argument("--coin", required=True)
    parser.add_argument("--symbol", required=True)
    parser.add_argument("--start-date", required=True)
    parser.add_argument("--end-date")
    parser.add_argument("--output", required=True)
    parser.add_argument("--collector-version", required=True)
    parser.add_argument("--collection-run-id")
    parser.add_argument("--max-days", type=int, default=3)
    parser.add_argument("--max-events-per-day", type=int, default=2_000_000)
    parser.add_argument("--rotate-mb", type=int, default=256)
    parser.add_argument("--stream-type")
    parser.add_argument(
        "--source-url",
        help="Explicit official archive URL (required for OKX; one bounded archive/day)",
    )
    args = parser.parse_args()

    start = date.fromisoformat(args.start_date)
    end = date.fromisoformat(args.end_date or args.start_date)
    days = iter_days(start, end, max_days=args.max_days)
    if args.venue == "okx" and len(days) != 1:
        raise SystemExit("OKX_EXPLICIT_SOURCE_URL_REQUIRES_SINGLE_DAY")
    root = Path(args.output)
    raw = root / "raw"
    bundle = root / "bundle"
    writer = PartitionedTickDatasetWriter(
        raw,
        rotate_bytes=max(1, int(args.rotate_mb)) * 1024 * 1024,
        flush_every=1000,
    )

    archives = []
    total = 0
    for day in days:
        result = fetch_official_archive_stream(
            venue=args.venue,
            coin=args.coin,
            symbol=args.symbol,
            day=day,
            max_events=max(1, int(args.max_events_per_day)),
            stream_type=args.stream_type,
            source_url=args.source_url,
        )
        stats = ArchiveObservationStats()
        batch = []
        for event in result.events:
            batch.append(event)
            stats.observe_exchange_ts(event.exchange_ts_ms)
            if len(batch) >= 5000:
                writer.append_batch(batch)
                batch.clear()
        if batch:
            writer.append_batch(batch)
        if stats.event_count <= 0:
            raise SystemExit(f"NO_ARCHIVE_EVENTS:{day.isoformat()}")
        total += stats.event_count
        archives.append({
            "venue": result.venue,
            "coin": result.coin,
            "symbol": result.symbol,
            "date": result.day.isoformat(),
            "source_url": result.source_url,
            "compressed_sha256": result.compressed_sha256,
            "checksum_verified": result.checksum_verified,
            "stream_type": result.stream_type,
            "event_count": stats.event_count,
            "first_exchange_ts_ms": stats.first_exchange_ts_ms,
            "last_exchange_ts_ms": stats.last_exchange_ts_ms,
            "timestamp_semantics": stats.timestamp_semantics,
        })

    shards = writer.rotate_all()
    if total <= 0 or not shards:
        raise SystemExit("NO_ARCHIVE_EVENTS")
    index = build_bundle(
        raw,
        bundle,
        collector_version=args.collector_version,
        collection_run_id=args.collection_run_id,
        collection_config={
            "venue": args.venue,
            "coin": args.coin.upper(),
            "symbol": args.symbol.upper(),
            "start_date": start.isoformat(),
            "end_date": end.isoformat(),
            "max_days": max(1, int(args.max_days)),
            "max_events_per_day": max(1, int(args.max_events_per_day)),
            "stream_type": args.stream_type,
            "archive_enabled": True,
            "read_only": True,
        },
        continuation_cursor={
            "last_date": days[-1].isoformat(),
            "last_exchange_ts_ms": archives[-1]["last_exchange_ts_ms"],
        },
    )
    summary = {
        "schema": "alina.official_archive_backfill.v1",
        "venue": args.venue,
        "coin": args.coin.upper(),
        "symbol": args.symbol.upper(),
        "start_date": start.isoformat(),
        "end_date": end.isoformat(),
        "event_count": total,
        "raw_shard_count": len(shards),
        "bundle_shard_count": index.get("shard_count"),
        "bundle_safe_count": index.get("safe_count"),
        "bundle_partial_count": index.get("partial_count"),
        "archives": archives,
        "bundle_path": str(bundle),
        "read_only": True,
        "real_execution": False,
    }
    root.mkdir(parents=True, exist_ok=True)
    (root / "archive_summary.json").write_text(
        json.dumps(summary, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(summary, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
