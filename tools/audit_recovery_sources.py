#!/usr/bin/env python3
"""Fail-closed, read-only comparison of unresolved shards against a Release inventory.

No downloaded data or manifest semantics are certified here. An inventory can be
stale; even a matching digest is only a published-source locator, NOT a SAFE
recovery or a proof that the asset is currently reachable.
"""
from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import re
from collections import Counter
from pathlib import Path
from typing import Any, Mapping

try:
    from tools.partitioned_data_index import read_index
    from tools.preservation_inventory import (
        InventoryError, iter_recovery_triage, summarize, verify_recovery_triage,
    )
except ModuleNotFoundError:
    from partitioned_data_index import read_index
    from preservation_inventory import (
        InventoryError, iter_recovery_triage, summarize, verify_recovery_triage,
    )

REPO = Path(__file__).resolve().parents[1]
CANONICAL = "Rapt0r06300/hyperliquid-smart-wallet-observer"
SHA = re.compile(r"[0-9a-f]{64}\Z")


def read_source_inventory(path: Path) -> tuple[dict[tuple[str, str], tuple[int, str]], dict[str, Any]]:
    """Validate global counts and every immutable outer-asset identity."""
    if path.is_symlink() or not path.is_file():
        raise InventoryError("SOURCE_INVENTORY_UNSAFE_OR_MISSING")
    opener = gzip.open if path.suffix == ".gz" else open
    with opener(path, "rt", encoding="utf-8") as source:
        inventory = json.load(source)
    if (not isinstance(inventory, dict)
            or inventory.get("schema") != "alina.restore_inventory.v1"
            or inventory.get("repository") != CANONICAL
            or not isinstance(inventory.get("generated_at_utc"), str)
            or not inventory["generated_at_utc"]
            or not isinstance(inventory.get("releases"), list)):
        raise InventoryError("SOURCE_INVENTORY_INVALID_HEADER")
    if any(type(inventory.get(k)) is not int or inventory[k] < 0
           for k in ("release_count", "asset_count", "source_asset_bytes")):
        raise InventoryError("SOURCE_INVENTORY_INVALID_TOTALS")
    seen_tags: set[str] = set()
    seen_release_ids: set[int] = set()
    seen_asset_ids: set[int] = set()
    assets: dict[tuple[str, str], tuple[int, str]] = {}
    total_bytes = 0
    total_assets = 0
    for release in inventory["releases"]:
        if not isinstance(release, Mapping):
            raise InventoryError("SOURCE_INVENTORY_INVALID_RELEASE")
        tag = release.get("tag_name")
        release_id = release.get("id")
        members = release.get("assets")
        if (not isinstance(tag, str) or not tag or tag in seen_tags
                or type(release_id) is not int or release_id <= 0
                or release_id in seen_release_ids or not isinstance(members, list)):
            raise InventoryError("SOURCE_INVENTORY_DUPLICATE_RELEASE")
        seen_tags.add(tag)
        seen_release_ids.add(release_id)
        for asset in members:
            if not isinstance(asset, Mapping):
                raise InventoryError("SOURCE_INVENTORY_INVALID_ASSET")
            name = asset.get("name")
            size = asset.get("size")
            digest = asset.get("digest")
            state = asset.get("state")
            asset_id = asset.get("id")
            if (not isinstance(name, str) or not name
                    or type(asset_id) is not int or asset_id <= 0
                    or type(size) is not int or size < 0
                    or not isinstance(digest, str)
                    or not digest.startswith("sha256:")
                    or not SHA.fullmatch(digest[7:].lower())
                    or state != "uploaded"):
                raise InventoryError("SOURCE_INVENTORY_INVALID_ASSET")
            key = (tag, name)
            if key in assets or asset_id in seen_asset_ids:
                raise InventoryError("SOURCE_INVENTORY_DUPLICATE_ASSET")
            seen_asset_ids.add(asset_id)
            assets[key] = (size, digest[7:].lower())
            total_assets += 1
            total_bytes += size
    if (len(seen_tags) != inventory["release_count"]
            or total_assets != inventory["asset_count"]
            or total_bytes != inventory["source_asset_bytes"]):
        raise InventoryError("SOURCE_INVENTORY_TOTALS_MISMATCH")
    return assets, {
        "source_snapshot_generated_at_utc": inventory["generated_at_utc"],
        "source_snapshot_releases": len(seen_tags),
        "source_snapshot_assets": total_assets,
        "source_snapshot_asset_bytes": total_bytes,
        "source_inventory_file_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
    }


def assess_sources(index: Mapping[str, Any], report: Mapping[str, Any],
                   assets: Mapping[tuple[str, str], tuple[int, str]],
                   source_metadata: Mapping[str, Any]) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Cross-check the complete unresolved queue; do not infer recoverability."""
    results: list[dict[str, Any]] = []
    counts: Counter[str] = Counter()
    by_status: dict[str, Counter[str]] = {}
    matched_outer: dict[tuple[str, str], int] = {}
    rows_by_id = {row["dataset_id"]: row for row in index["shards"]}
    if len(rows_by_id) != len(index["shards"]):
        raise InventoryError("SOURCE_AUDIT_DUPLICATE_CATALOG_ID")
    for row in iter_recovery_triage(index):
        tag = row.get("release_tag")
        inner = row.get("release_asset")
        container = row.get("release_container_asset")
        name = container or inner
        key = (tag, name)
        missing = list(row["missing_evidence"])
        decision = "INDEX_IDENTITY_INCOMPLETE"
        if (not isinstance(tag, str) or not tag
                or not isinstance(name, str) or not name
                or "canonical_release_repository" in missing):
            decision = "INDEX_IDENTITY_INCOMPLETE"
        elif key not in assets:
            decision = "NOT_LISTED_IN_SNAPSHOT"
        else:
            size, digest = assets[key]
            # Packed sharded assets are validated at the outer ZIP identity.
            original = rows_by_id.get(row["dataset_id"])
            if original is None:
                raise InventoryError("SOURCE_AUDIT_MISSING_CATALOG_ROW")
            if container:
                expected_size = original.get("release_remote_size")
                expected_digest = original.get("release_remote_digest")
            else:
                expected_size = original.get("bytes")
                expected_digest = original.get("sha256")
            expected_digest = (expected_digest.removeprefix("sha256:").lower()
                               if isinstance(expected_digest, str) else None)
            if (type(expected_size) is not int or expected_size < 0
                    or not isinstance(expected_digest, str)
                    or not SHA.fullmatch(expected_digest)):
                decision = "SNAPSHOT_LISTED_IDENTITY_UNBOUND"
            elif expected_size != size or expected_digest != digest:
                decision = "SNAPSHOT_METADATA_CONFLICT"
            elif any(field in missing for field in ("release_asset", "sha256", "bytes")):
                # A matched ZIP does not identify an unverified inner member.
                decision = "SNAPSHOT_LISTED_IDENTITY_UNBOUND"
            else:
                decision = "SNAPSHOT_ASSET_IDENTITY_MATCHED_NOT_DOWNLOADED"
                matched_outer[key] = size
        counts[decision] += 1
        quality = row["quality_status"]
        by_status.setdefault(quality, Counter())[decision] += 1
        results.append({
            "dataset_id": row["dataset_id"],
            "quality_status": quality, "family": row["family"],
            "source_tag": tag, "source_asset": name,
            "source_comparison": decision, "missing_evidence": missing,
            "recovery_status": "NOT_ASSESSED", "validation_allowed": False,
        })
    expected = report["unresolved_unsafe_shards"] + report["safe_non_replayable_shards"]
    if len(results) != expected:
        raise InventoryError("SOURCE_AUDIT_CANDIDATE_COUNT_MISMATCH")
    summary = {
        "schema": "alina.recovery_source_audit.v1",
        "status": "SOURCE_SNAPSHOT_COMPARED_NOT_RESTORED",
        "catalog_index_sha256": report["catalog_index_sha256"],
        **source_metadata,
        "candidate_count": len(results),
        "source_classification_counts": dict(sorted(counts.items())),
        "by_quality_status": {k: dict(sorted(v.items())) for k, v in sorted(by_status.items())},
        "unique_matched_outer_assets": len(matched_outer),
        "unique_matched_outer_asset_bytes": sum(matched_outer.values()),
        "recovered_shards": None, "irrecoverable_shards": None,
        "source_snapshot_currently_reachable": False,
        "all_exploitable_data_restored": False,
        "note": ("A past inventory is not a live GitHub availability check. "
                 "Matching asset identity does not prove byte hydration, "
                 "shard continuity, replay compatibility or recovered trades."),
    }
    return summary, results


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--index", type=Path, default=REPO / "catalog/DATA_INDEX.json")
    parser.add_argument("--metrics", type=Path, default=REPO / "catalog/DATA_METRICS.json")
    parser.add_argument("--triage-jsonl", type=Path, required=True,
                        help="Previously verified, canonical SHA-bound triage ledger")
    parser.add_argument("--source-inventory", type=Path, required=True,
                        help="RESTORE_INVENTORY.json.gz from immutable GitHub Release")
    parser.add_argument("--details-jsonl", type=Path,
                        help="New file for read-only per-shard source comparisons")
    args = parser.parse_args(argv)
    try:
        raw = args.index.read_bytes()
        index = read_index(args.index)
        metrics = json.loads(args.metrics.read_text(encoding="utf-8"))
        report = summarize(index, metrics, hashlib.sha256(raw).hexdigest())
        verify_recovery_triage(index, report, args.triage_jsonl)
        assets, metadata = read_source_inventory(args.source_inventory)
        outcome, details = assess_sources(index, report, assets, metadata)
        if args.details_jsonl is not None:
            path = args.details_jsonl
            if path.exists() or path.is_symlink() or not path.parent.is_dir() or path.parent.is_symlink():
                raise InventoryError("SOURCE_AUDIT_REFUSE_OVERWRITE")
            # A failed audit must not leave a misleading finished ledger.
            import os
            import tempfile
            temp = None
            try:
                with tempfile.NamedTemporaryFile("w", encoding="utf-8",
                        newline="\n", dir=path.parent, prefix=".source-audit-",
                        suffix=".tmp", delete=False) as stream:
                    temp = Path(stream.name)
                    for row in details:
                        stream.write(json.dumps(row, sort_keys=True) + "\n")
                    stream.flush()
                    os.fsync(stream.fileno())
                os.link(temp, path)
            finally:
                if temp is not None:
                    temp.unlink(missing_ok=True)
        print(json.dumps(outcome, indent=2, sort_keys=True))
        return 0
    except (OSError, ValueError, TypeError) as exc:
        print(json.dumps({"status": "SOURCE_AUDIT_INCOMPLETE", "reason": str(exc)}, sort_keys=True))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
