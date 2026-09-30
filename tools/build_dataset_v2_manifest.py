#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path

from hl_observer.datasets.v2_export import (
    build_manifest_from_tick_shard,
    write_manifest,
)


def main() -> int:
    parser = argparse.ArgumentParser(description="Build an Alina dataset V2 manifest from one immutable tick shard.")
    parser.add_argument("shard")
    parser.add_argument("--collector-version", required=True)
    parser.add_argument("--output")
    parser.add_argument("--reconciliation-status", default="UNVERIFIED")
    parser.add_argument("--required-channel", action="append", default=[])
    parser.add_argument("--cost-model-applicable", action="store_true")
    parser.add_argument("--cost-model-ready", action="store_true")
    args = parser.parse_args()

    manifest = build_manifest_from_tick_shard(
        args.shard,
        collector_version=args.collector_version,
        reconciliation_status=args.reconciliation_status,
        required_channels=args.required_channel,
        cost_model_applicable=args.cost_model_applicable,
        cost_model_ready=args.cost_model_ready,
    )
    if args.output:
        write_manifest(manifest, args.output)
    print(json.dumps(manifest, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
