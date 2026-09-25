"""CLI for SAFE-only Alina Dataset V2 selection/materialization."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from hl_observer.datasets.v2_repository import (
    DatasetV2Error,
    load_index,
    materialize_safe_shards,
    select_safe_shards,
)


def _csv(value: str) -> list[str]:
    return [item.strip() for item in str(value or "").split(",") if item.strip()]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Select or materialize only SAFE shards from Alina Dataset V2."
    )
    parser.add_argument("action", choices=("plan", "materialize"))
    parser.add_argument("--output", default="data/alina_dataset_v2/materialized")
    parser.add_argument("--families", default="")
    parser.add_argument("--venues", default="")
    parser.add_argument("--symbols", default="")
    parser.add_argument("--start-ts-ms", type=int)
    parser.add_argument("--end-ts-ms", type=int)
    parser.add_argument(
        "--max-shards",
        type=int,
        default=0,
        help="Bound materialization to the newest N matching SAFE shards (0 = all).",
    )
    args = parser.parse_args(argv)

    try:
        index, digest = load_index()
        shards = select_safe_shards(
            index,
            families=_csv(args.families),
            venues=_csv(args.venues),
            symbols=_csv(args.symbols),
            start_ts_ms=args.start_ts_ms,
            end_ts_ms=args.end_ts_ms,
        )
        if args.max_shards and args.max_shards > 0:
            shards = shards[-int(args.max_shards):]
        plan = {
            "schema": "alina.dataset_v2_materialization_plan.v1",
            "index_sha256": digest,
            "safe_shards": len(shards),
            "events": sum(item.event_count for item in shards),
            "bytes": sum(item.bytes for item in shards),
            "dataset_ids": [item.dataset_id for item in shards],
            "legacy_import": False,
            "real_execution": False,
        }
        if args.action == "plan":
            print(json.dumps(plan, indent=2, sort_keys=True))
            return 0
        if not shards:
            raise DatasetV2Error("no SAFE shards match the selection")
        result = materialize_safe_shards(
            shards,
            Path(args.output),
            index_sha256=digest,
        )
        print(json.dumps({"plan": plan, "materialized": result}, indent=2, sort_keys=True))
        return 0
    except (DatasetV2Error, OSError, ValueError) as exc:
        print(f"DATASET_V2_NO_GO: {exc}")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
