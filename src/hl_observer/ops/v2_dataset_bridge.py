"""CLI for provenance-complete SAFE-only Alina Dataset V2 materialization."""
from __future__ import annotations

import argparse
import json
import re
from collections import Counter
from pathlib import Path

from hl_observer.datasets.v2_repository import (
    DatasetV2Error,
    load_index,
    materialize_safe_shards,
    select_safe_shards,
)

_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_TRADE_FAMILIES = {"trades", "agg_trades", "fills", "userfills", "user_fills", "copy_vault_fills"}


def _balanced_recent_shards(shards, limit: int):
    if limit <= 0 or len(shards) <= limit:
        return list(shards)
    buckets = {}
    for shard in shards:
        buckets.setdefault((shard.venue, shard.family), []).append(shard)
    for rows in buckets.values():
        rows.sort(key=lambda row: (row.end_ts_ms, row.dataset_id), reverse=True)
    selected = []
    keys = sorted(buckets)
    while len(selected) < limit:
        progressed = False
        for key in keys:
            if buckets[key] and len(selected) < limit:
                selected.append(buckets[key].pop(0))
                progressed = True
        if not progressed:
            break
    return sorted(selected, key=lambda row: (row.start_ts_ms, row.dataset_id))


def _csv(value: str) -> list[str]:
    return [item.strip() for item in str(value or "").split(",") if item.strip()]


def _require_provenance(args: argparse.Namespace) -> None:
    if not _SHA256.fullmatch(str(args.dataset_selection_id or "").lower()):
        raise DatasetV2Error("dataset_selection_id must be an exact SHA-256")
    if args.source_collection_epoch is None or args.source_collection_epoch < 0:
        raise DatasetV2Error("source_collection_epoch is required and must be non-negative")
    if not str(args.collection_cutoff_at_utc or "").strip():
        raise DatasetV2Error("collection_cutoff_at_utc is required")
    if args.start_ts_ms is not None and args.end_ts_ms is not None and args.end_ts_ms < args.start_ts_ms:
        raise DatasetV2Error("end_ts_ms precedes start_ts_ms")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Select or materialize only SAFE replay-compatible Dataset V2 shards.")
    parser.add_argument("action", choices=("plan", "materialize"))
    parser.add_argument("--output", default="data/alina_dataset_v2/materialized")
    parser.add_argument("--families", default="")
    parser.add_argument("--venues", default="")
    parser.add_argument("--symbols", default="")
    parser.add_argument("--start-ts-ms", type=int)
    parser.add_argument("--end-ts-ms", type=int)
    parser.add_argument("--dataset-selection-id")
    parser.add_argument("--source-collection-epoch", type=int)
    parser.add_argument("--collection-cutoff-at-utc")
    parser.add_argument("--max-shards", type=int, default=0, help="Balanced recent venue/family bound (0 = all).")
    parser.add_argument("--require-trade-events", action="store_true")
    args = parser.parse_args(argv)

    try:
        if args.action == "materialize":
            _require_provenance(args)
        elif args.start_ts_ms is not None and args.end_ts_ms is not None and args.end_ts_ms < args.start_ts_ms:
            raise DatasetV2Error("end_ts_ms precedes start_ts_ms")
        if args.max_shards < 0:
            raise DatasetV2Error("max_shards must be non-negative")
        index, digest = load_index()
        shards = select_safe_shards(
            index,
            families=_csv(args.families),
            venues=_csv(args.venues),
            symbols=_csv(args.symbols),
            start_ts_ms=args.start_ts_ms,
            end_ts_ms=args.end_ts_ms,
        )
        if args.max_shards:
            shards = _balanced_recent_shards(shards, args.max_shards)
        if not shards:
            raise DatasetV2Error("no SAFE replay-compatible shards match the selection")
        trade_shards = [row for row in shards if row.family.lower() in _TRADE_FAMILIES and row.event_count > 0]
        if args.require_trade_events and not trade_shards:
            raise DatasetV2Error("selection contains no SAFE trade events")
        by_family = Counter(row.family for row in shards)
        by_venue = Counter(row.venue for row in shards)
        plan = {
            "schema": "alina.dataset_v2_materialization_plan.v2",
            "index_sha256": digest,
            "safe_shards": len(shards),
            "events": sum(item.event_count for item in shards),
            "bytes": sum(item.bytes for item in shards),
            "selection_by_family": dict(sorted(by_family.items())),
            "selection_by_venue": dict(sorted(by_venue.items())),
            "trade_event_shards": len(trade_shards),
            "trade_events": sum(item.event_count for item in trade_shards),
            "dataset_ids": [item.dataset_id for item in shards],
            "dataset_selection_id": (
                args.dataset_selection_id.lower()
                if args.dataset_selection_id is not None
                else None
            ),
            "source_collection_epoch": args.source_collection_epoch,
            "collection_cutoff_at_utc": args.collection_cutoff_at_utc,
            "provenance_complete": (
                args.dataset_selection_id is not None
                and args.source_collection_epoch is not None
                and args.collection_cutoff_at_utc is not None
            ),
            "quality_status_required": "SAFE",
            "replay_compatible_required": True,
            "legacy_import": False,
            "paper_only": True,
            "real_execution": False,
        }
        if args.action == "plan":
            print(json.dumps(plan, indent=2, sort_keys=True))
            return 0
        result = materialize_safe_shards(
            shards,
            Path(args.output),
            index_sha256=digest,
            dataset_selection_id=plan["dataset_selection_id"],
            source_collection_epoch=plan["source_collection_epoch"],
            collection_cutoff_at_utc=plan["collection_cutoff_at_utc"],
        )
        print(json.dumps({"plan": plan, "materialized": result}, indent=2, sort_keys=True))
        return 0
    except (DatasetV2Error, OSError, ValueError) as exc:
        print(f"DATASET_V2_NO_GO: {exc}")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
