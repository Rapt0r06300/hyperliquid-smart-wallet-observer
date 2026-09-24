#!/usr/bin/env python3
"""Collect a bounded public Event Intelligence window into Dataset V2."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from hl_observer.event_intelligence.dataset_v2 import build_public_event_bundle


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--collector-version", required=True)
    parser.add_argument("--collection-run-id", required=True)
    args = parser.parse_args()
    result = build_public_event_bundle(
        output_root=args.output,
        collector_version=args.collector_version,
        collection_run_id=args.collection_run_id,
    )
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
