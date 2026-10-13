#!/usr/bin/env python3
"""Opt-in, SHA-verified bounded hydration of non-SAFE Release evidence.

DRY RUN by default. Uses the canonical restore downloader and archive cache;
never deletes evidence, never reclassifies shards, never certifies replay/PnL.
Only download from the canonical GitHub repository on explicit --execute.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from collections import Counter
from pathlib import Path
from typing import Any, Mapping
from urllib.parse import quote

try:
    from tools.audit_recovery_sources import read_source_inventory
    from tools.partitioned_data_index import read_index
    from tools.preservation_inventory import InventoryError, iter_recovery_triage, summarize, verify_recovery_triage
    from tools.restore_alina import (
        RestoreError, _asset_ok, _safe_component, download_asset,
    )
except ModuleNotFoundError:
    from audit_recovery_sources import read_source_inventory
    from partitioned_data_index import read_index
    from preservation_inventory import InventoryError, iter_recovery_triage, summarize, verify_recovery_triage
    from restore_alina import RestoreError, _asset_ok, _safe_component, download_asset

REPO_ROOT = Path(__file__).resolve().parents[1]
CANONICAL = "Rapt0r06300/hyperliquid-smart-wallet-observer"


def select_assets(index: Mapping[str, Any],
                  assets: Mapping[tuple[str, str], tuple[int, str]],
                  *, max_assets: int = 10,
                  max_bytes: int = 2_000_000_000,
                  asset_offset: int = 0) -> dict[str, Any]:
    if type(max_assets) is not int or not 1 <= max_assets <= 1000:
        raise InventoryError("HYDRATE_INVALID_ASSET_LIMIT")
    if type(asset_offset) is not int or asset_offset < 0:
        raise InventoryError("HYDRATE_INVALID_ASSET_OFFSET")
    if type(max_bytes) is not int or not 1 <= max_bytes <= 10_000_000_000:
        raise InventoryError("HYDRATE_INVALID_BYTE_LIMIT")
    rows = index.get("shards")
    if not isinstance(rows, list):
        raise InventoryError("HYDRATE_MISSING_CATALOG_ROWS")
    rows_by_id = {item["dataset_id"]: item for item in rows}
    if len(rows_by_id) != len(rows):
        raise InventoryError("HYDRATE_DUPLICATE_INDEX_ID")
    seen = set()
    eligible_seen = 0
    selected = []
    reasons = Counter()
    candidate_count = 0
    selected_bytes = 0
    for row in iter_recovery_triage(index):
        candidate_count += 1
        if row["missing_evidence"] or not row["release_tag"] or not row["release_asset"]:
            reasons["INDEX_EVIDENCE_INCOMPLETE"] += 1
            continue
        tag = row["release_tag"]
        outer = row.get("release_container_asset") or row["release_asset"]
        key = (tag, outer)
        if key not in assets:
            reasons["NOT_LISTED_IN_SNAPSHOT"] += 1
            continue
        size, digest = assets[key]
        raw = rows_by_id.get(row["dataset_id"])
        if raw is None:
            raise InventoryError("HYDRATE_CATALOG_ID_MISSING")
        packed = bool(row.get("release_container_asset"))
        expected_size = raw.get("release_remote_size") if packed else raw.get("bytes")
        expected_hash = raw.get("release_remote_digest") if packed else raw.get("sha256")
        expected_hash = expected_hash.removeprefix("sha256:").lower() if isinstance(expected_hash, str) else ""
        if expected_size != size or expected_hash != digest:
            # The same outer Release archive must never be selected based
            # on one matching shard while another indexed shard disagrees.
            if key in seen:
                raise InventoryError("HYDRATE_SHARED_OUTER_ASSET_IDENTITY_CONFLICT")
            reasons["OUTER_IDENTITY_CONFLICT"] += 1
            continue
        if key in seen:
            continue
        seen.add(key)
        eligible_seen += 1
        if eligible_seen <= asset_offset:
            continue
        if len(selected) >= max_assets or selected_bytes + size > max_bytes:
            reasons["BUDGET_DEFERRED"] += 1
            continue
        selected.append({
            "release_tag": tag, "asset_name": outer,
            "size_bytes": size, "sha256": digest,
            "source_url": (
                f"https://github.com/{CANONICAL}/releases/download/"
                + quote(tag, safe="") + "/" + quote(outer, safe="")
            ),
        })
        selected_bytes += size
    return {
        "status": "HYDRATION_PLAN_NOT_REPLAY_CERTIFIED",
        "candidate_shards": candidate_count,
        "eligible_unique_outer_assets": eligible_seen,
        "asset_offset": asset_offset,
        "selected_unique_outer_assets": len(selected),
        "selected_source_asset_bytes": selected_bytes,
        "deferred_or_excluded_outer_assets_by_reason": dict(sorted(reasons.items())),
        "selection": selected,
        "complete_coverage_claimed": False,
        "replay_certified": False,
    }


def hydrate_selected(plan: Mapping[str, Any], releases_root: Path,
                     *, execute: bool = False, token: str | None = None) -> dict[str, Any]:
    output = Path(releases_root)
    if output.is_symlink() or not output.is_dir():
        raise InventoryError("HYDRATE_OUTPUT_MUST_EXIST_NOT_SYMLINK")
    outcomes: list[dict[str, Any]] = []
    for row in plan["selection"]:
        tag, name = row["release_tag"], row["asset_name"]
        directory = output / _safe_component(tag)
        dest = directory / _safe_component(name)
        info = {
            "release_tag": tag, "asset_name": name,
            "expected_size": row["size_bytes"],
            "expected_sha256": row["sha256"],
        }
        if directory.is_symlink() or dest.is_symlink():
            outcome = "SYMLINK_REFUSED"
        elif dest.exists():
            if _asset_ok(dest, {"size": row["size_bytes"],
                                "digest": "sha256:" + row["sha256"]}):
                outcome = "ALREADY_VERIFIED"
            else:
                outcome = "CACHE_CONFLICT_PRESERVED"
        elif not execute:
            outcome = "NOT_DOWNLOADED_DRY_RUN"
        elif (directory / (_safe_component(name) + ".partial")).exists():
            outcome = "PARTIAL_CACHE_PRESERVED_NOT_OVERWRITTEN"
        else:
            try:
                directory.mkdir(parents=True, exist_ok=True)
                receipt = download_asset({
                    "name": name,
                    "browser_download_url": row["source_url"],
                    "size": row["size_bytes"],
                    "digest": "sha256:" + row["sha256"],
                }, directory, token=token)
                outcome = (
                    "BYTES_VERIFIED_QUARANTINE_ONLY"
                    if receipt["verification_status"] == "VERIFIED"
                    else "DOWNLOAD_NOT_VERIFIED"
                )
            except (OSError, RestoreError) as exc:
                outcome = "DOWNLOAD_NOT_VERIFIED"
                info["error_type"] = type(exc).__name__
        outcomes.append({**info, "status": outcome})
    return {
        "schema": "alina.recovery_asset_hydration.v1",
        "status": "CACHED_RELEASE_BYTES_ONLY_NOT_REPLAY_CERTIFIED",
        "executed": bool(execute),
        "source_assets_selected": len(plan["selection"]),
        "source_asset_outcomes": outcomes,
        "downloaded_or_reused_verified_assets": sum(
            x["status"] in {"ALREADY_VERIFIED", "BYTES_VERIFIED_QUARANTINE_ONLY"} for x in outcomes
        ),
        "replay_certified": False,
        "recovered_shards": None,
        "all_exploitable_data_restored": False,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--index", type=Path, default=REPO_ROOT / "catalog/DATA_INDEX.json")
    parser.add_argument("--metrics", type=Path, default=REPO_ROOT / "catalog/DATA_METRICS.json")
    parser.add_argument("--triage-jsonl", type=Path, required=True)
    parser.add_argument("--source-inventory", type=Path, required=True)
    parser.add_argument("--releases-root", type=Path, required=True)
    parser.add_argument("--max-assets", type=int, default=10)
    parser.add_argument("--asset-offset", type=int, default=0)
    parser.add_argument("--max-bytes", type=int, default=2_000_000_000)
    parser.add_argument("--execute", action="store_true")
    args = parser.parse_args(argv)
    try:
        raw = args.index.read_bytes()
        index = read_index(args.index)
        metrics = json.loads(args.metrics.read_text(encoding="utf-8"))
        proof = summarize(index, metrics, hashlib.sha256(raw).hexdigest())
        verify_recovery_triage(index, proof, args.triage_jsonl)
        assets, inventory_metadata = read_source_inventory(args.source_inventory)
        plan = select_assets(index, assets, max_assets=args.max_assets,
                             max_bytes=args.max_bytes, asset_offset=args.asset_offset)
        hydration = hydrate_selected(
            plan, args.releases_root, execute=args.execute,
            token=__import__("os").environ.get("GH_TOKEN")
                or __import__("os").environ.get("GITHUB_TOKEN"),
        )
        output = {"catalog_index_sha256": proof["catalog_index_sha256"],
                  "source_inventory_file_sha256": inventory_metadata["source_inventory_file_sha256"],
                  "selection": plan,
                  "hydration": hydration}
    except (OSError, ValueError, TypeError, RestoreError) as exc:
        print(json.dumps({"status": "HYDRATION_INCOMPLETE", "reason": str(exc)}, sort_keys=True))
        return 2
    print(json.dumps(output, sort_keys=True))
    return 0 if not args.execute or (
        hydration["downloaded_or_reused_verified_assets"] == plan["selected_unique_outer_assets"]
    ) else 2


if __name__ == "__main__":
    raise SystemExit(main())
