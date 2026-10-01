#!/usr/bin/env python3
"""Resolve one frozen Dataset V2 selection identity for a whole ANALYZE epoch."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path


def digest_bytes(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def resolve_selection(
    root: Path,
    *,
    epoch: int,
    source_collection_epoch: int,
    collection_cutoff_at_utc: str,
) -> str:
    campaign_root = root / "catalog" / "campaigns"
    existing: set[str] = set()
    if campaign_root.exists():
        for path in sorted(campaign_root.glob("*.json")):
            try:
                row = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, ValueError, TypeError):
                continue
            if (
                isinstance(row, dict)
                and row.get("schema_version") == "alina.resumable_campaign.v2"
                and row.get("creation_phase") == "ANALYZE"
                and int(row.get("phase_epoch") or 0) == epoch
                and row.get("source_collection_epoch") == source_collection_epoch
                and row.get("dataset_selection_id")
            ):
                existing.add(str(row["dataset_selection_id"]))

    if len(existing) > 1:
        raise SystemExit(
            "analysis selection drift detected: " + ",".join(sorted(existing))
        )
    if existing:
        selection = next(iter(existing))
        if len(selection) != 64 or any(ch not in "0123456789abcdef" for ch in selection):
            raise SystemExit("existing analysis selection id is not canonical sha256")
        return selection

    index_path = root / "catalog" / "DATA_INDEX.json"
    if not index_path.is_file():
        raise SystemExit("catalog/DATA_INDEX.json is required to freeze analysis selection")
    index_sha = digest_bytes(index_path)
    material = (
        f"{source_collection_epoch}|{collection_cutoff_at_utc}|{index_sha}"
    ).encode("utf-8")
    return hashlib.sha256(material).hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", default=".")
    parser.add_argument("--epoch", type=int, required=True)
    parser.add_argument("--source-collection-epoch", type=int, required=True)
    parser.add_argument("--collection-cutoff-at-utc", required=True)
    args = parser.parse_args()
    if args.epoch < 1 or args.source_collection_epoch < 1:
        raise SystemExit("epochs must be positive")
    if not str(args.collection_cutoff_at_utc).endswith("Z"):
        raise SystemExit("collection cutoff must be UTC and end in Z")
    print(
        resolve_selection(
            Path(args.root),
            epoch=args.epoch,
            source_collection_epoch=args.source_collection_epoch,
            collection_cutoff_at_utc=args.collection_cutoff_at_utc,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
