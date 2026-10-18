#!/usr/bin/env python3
"""Inventory physical Release containers with mixed SAFE/non-SAFE members.

Metadata-only: never claims that a remote asset or its bytes were verified.
Run on a GitHub-hosted runner against the exact partitioned index on main.
"""
from __future__ import annotations

import argparse
import json
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

try:
    from tools.index_run_manifest import hydrate_default_release_repository
    from tools.partitioned_data_index import read_index
except ModuleNotFoundError:
    from index_run_manifest import hydrate_default_release_repository
    from partitioned_data_index import read_index

CANONICAL = "Rapt0r06300/hyperliquid-smart-wallet-observer"


def inventory(rows: list[dict[str, Any]], *, sample_limit: int = 20) -> dict[str, Any]:
    groups: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    missing_locator = Counter()
    for row in rows:
        status = str(row.get("quality_status") or "UNKNOWN").upper()
        repo = str(row.get("release_repository") or CANONICAL)
        tag = str(row.get("release_tag") or "")
        physical = str(row.get("release_container_asset") or row.get("release_asset") or "")
        if repo != CANONICAL or not tag or not physical:
            missing_locator[status] += 1
            continue
        groups[(tag, physical)].append(row)
    mixed = []
    with_reject = reject_only = safe_reject = mixed_bytes = inconsistent = mixed_total = 0
    for (tag, asset), members in sorted(groups.items()):
        counts = Counter(str(r.get("quality_status") or "UNKNOWN").upper() for r in members)
        if counts["REJECT"]:
            with_reject += 1
            if len(counts) == 1:
                reject_only += 1
            if counts["SAFE"]:
                safe_reject += 1
        if len(counts) < 2:
            continue
        mixed_total += 1
        digests = {str(r.get("release_remote_digest") or "") for r in members}
        sizes = {str(r.get("release_remote_size") or "") for r in members}
        conflicts = len(digests) != 1 or len(sizes) != 1 or not next(iter(digests))
        if conflicts:
            inconsistent += 1
        remote_bytes = next(iter(sizes)) if len(sizes) == 1 else ""
        if remote_bytes.isdecimal():
            mixed_bytes += int(remote_bytes)
        if len(mixed) < max(0, sample_limit):
            mixed.append({
                "release_tag": tag, "asset_name": asset,
                "member_status_counts": dict(sorted(counts.items())),
                "member_count": len(members),
                "remote_identity_conflict": conflicts,
                "remote_size": int(remote_bytes) if remote_bytes.isdecimal() else None,
                "dataset_ids_sample": [str(r.get("dataset_id") or "") for r in members[:5]],
            })
    return {
        "schema": "alina.mixed_release_asset_inventory.v1",
        "scope": "CANONICAL_CATALOG_LOCATORS_ONLY_NOT_REMOTE_ASSET_VERIFICATION",
        "indexed_shards": len(rows),
        "physical_assets_with_indexed_members": len(groups),
        "assets_with_reject_members": with_reject,
        "reject_only_assets": reject_only,
        "mixed_status_assets": mixed_total,
        "safe_and_reject_assets": safe_reject,
        "mixed_status_remote_bytes_declared": mixed_bytes,
        "mixed_with_inconsistent_remote_identity": inconsistent,
        "shards_without_canonical_physical_locator": dict(sorted(missing_locator.items())),
        "mixed_samples": mixed,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--index", type=Path, default=Path("catalog/DATA_INDEX.json"))
    parser.add_argument("--json-out", type=Path)
    parser.add_argument("--sample-limit", type=int, default=20)
    args = parser.parse_args()
    index = read_index(args.index)
    result = inventory(hydrate_default_release_repository(index), sample_limit=args.sample_limit)
    serialized = json.dumps(result, indent=2, sort_keys=True) + "\n"
    if args.json_out:
        args.json_out.parent.mkdir(parents=True, exist_ok=True)
        args.json_out.write_text(serialized, encoding="utf-8")
    print(serialized)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
