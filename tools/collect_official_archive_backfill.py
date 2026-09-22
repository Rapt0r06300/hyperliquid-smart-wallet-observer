#!/usr/bin/env python3
"""Collect bounded official Binance/Bybit public archives into dataset V2."""
from __future__ import annotations

import argparse
import json
from datetime import date
from pathlib import Path

from hl_observer.collection.partitioned_tick_dataset import PartitionedTickDatasetWriter
from hl_observer.data_sources.official_archive_backfill import fetch_official_archive_day, iter_days
from hl_observer.datasets.v2_pipeline import build_bundle


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--venue", choices=("binance", "bybit"), required=True)
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
    args = parser.parse_args()

    start = date.fromisoformat(args.start_date)
    end = date.fromisoformat(args.end_date or args.start_date)
    days = iter_days(start, end, max_days=args.max_days)
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
        result = fetch_official_archive_day(
            venue=args.venue,
            coin=args.coin,
            symbol=args.symbol,
            day=day,
            max_events=max(1, int(args.max_events_per_day)),
        )
        for offset in range(0, len(result.events), 5000):
            writer.append_batch(result.events[offset:offset + 5000])
        total += len(result.events)
        archives.append({
            "venue": result.venue,
            "coin": result.coin,
            "symbol": result.symbol,
            "date": result.day.isoformat(),
            "source_url": result.source_url,
            "compressed_sha256": result.compressed_sha256,
            "checksum_verified": result.checksum_verified,
            "event_count": len(result.events),
        })

    shards = writer.rotate_all()
    if total <= 0 or not shards:
        raise SystemExit("NO_ARCHIVE_EVENTS")
    index = build_bundle(
        raw,
        bundle,
        collector_version=args.collector_version,
        collection_run_id=args.collection_run_id,
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
