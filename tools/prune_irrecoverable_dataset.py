#!/usr/bin/env python3
"""Delete only terminal non-viable principal-dataset payloads, fail closed.

The workflow is deliberately three-phase: prepare and durably commit a SHA-bound
plan, delete exact verified GitHub Release assets, then finalize catalog removal.
SAFE data, active/unverified data, mixed SAFE containers and retryable failures
are never eligible.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from collections import defaultdict
from collections.abc import Mapping
from pathlib import Path
from typing import Any

try:
    from tools.index_run_manifest import (
        _atomic_json,
        _oversized_legacy_stage,
        _publish_canonical_index,
        compact_index_rows,
        hydrate_default_release_repository,
    )
    from tools.partitioned_data_index import read_index
    from tools.prune_verified_recovery_capsule import (
        REPOSITORY,
        Refuse,
        assets,
        release,
        request,
    )
    from tools.replay_compatibility import VERIFIER_VERSION
except ModuleNotFoundError:
    from index_run_manifest import (
        _atomic_json,
        _oversized_legacy_stage,
        _publish_canonical_index,
        compact_index_rows,
        hydrate_default_release_repository,
    )
    from partitioned_data_index import read_index
    from prune_verified_recovery_capsule import REPOSITORY, Refuse, assets, release, request
    from replay_compatibility import VERIFIER_VERSION

ROOT = Path(__file__).resolve().parents[1]
INDEX = ROOT / "catalog" / "DATA_INDEX.json"
METRICS = ROOT / "catalog" / "DATA_METRICS.json"
PATCH = ROOT / "catalog" / "REPLAY_COMPAT_PATCH.json"
PLAN = ROOT / "catalog" / "DATA_DELETION_PLAN.json"
HISTORY = ROOT / "catalog" / "DATA_DELETION_HISTORY.json"
TERMINAL = {"PARTIAL", "REJECT"}


def _refresh_catalog(index: dict[str, Any], root: Path) -> None:
    """Publish one lossless index mutation and its exact status counters."""
    rows = hydrate_default_release_repository(index)
    active = (
        "SAFE" if any(row.get("quality_status") == "SAFE" for row in rows)
        else ("PARTIAL" if rows else "NO_DATA")
    )
    index["active_data_status"] = active
    index["release_repository_default"] = REPOSITORY
    index["shards"] = compact_index_rows(index, rows)
    _publish_canonical_index(root / "catalog" / "DATA_INDEX.json", index)
    counts = {
        status: sum(row.get("quality_status") == status for row in rows)
        for status in ("SAFE", "PARTIAL", "STALE", "REJECT")
    }
    catalog = _load(root / "catalog" / "DATA_CATALOG.json")
    catalog.update({
        "active_data_status": active,
        "indexed_shard_count": len(rows),
        "safe_shard_count": counts["SAFE"],
        "partial_shard_count": counts["PARTIAL"],
        "stale_shard_count": counts["STALE"],
        "reject_shard_count": counts["REJECT"],
    })
    _atomic_json(root / "catalog" / "DATA_CATALOG.json", catalog)
    registry = _load(root / "catalog" / "DATA_QUALITY_REGISTRY.json")
    registry["active_dataset"] = {
        "status": active,
        "validation_allowed": active == "SAFE",
        "proof_of_pnl_allowed": False,
        "indexed_shards": len(rows),
        "safe_count": counts["SAFE"],
        "partial_count": counts["PARTIAL"],
        "stale_count": counts["STALE"],
        "reject_count": counts["REJECT"],
    }
    _atomic_json(root / "catalog" / "DATA_QUALITY_REGISTRY.json", registry)


def _load(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise Refuse(f"INVALID_JSON_OBJECT:{path}")
    return value


def _write(path: Path, value: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(dict(value), indent=2, sort_keys=True) + "\n", encoding="utf-8")
    os.replace(tmp, path)


def _digest(value: Mapping[str, Any]) -> str:
    body = {key: item for key, item in value.items() if key != "plan_digest"}
    raw = json.dumps(body, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(raw).hexdigest()


def _verified_snapshot() -> tuple[dict[str, Any], list[dict[str, Any]], str]:
    index_raw = INDEX.read_bytes()
    index = read_index(INDEX)
    rows = hydrate_default_release_repository(index)
    metrics = _load(METRICS)
    totals = metrics.get("totals")
    source_sha = hashlib.sha256(index_raw).hexdigest()
    if (
        metrics.get("schema_version") != "alina.data_metrics.v4"
        or metrics.get("source_index_sha256") != source_sha
        or not isinstance(totals, Mapping)
        or totals.get("TOTAL_SHARDS") != len(rows)
    ):
        raise Refuse("DELETION_STALE_OR_INCOMPLETE_METRICS")
    return index, rows, source_sha


def _physical_key(row: Mapping[str, Any]) -> tuple[str, str] | None:
    if (row.get("release_repository") or REPOSITORY) != REPOSITORY:
        return None
    tag = str(row.get("release_tag") or "")
    asset = str(row.get("release_container_asset") or row.get("release_asset") or "")
    return (tag, asset) if tag and asset else None


def _terminal_rows(
    rows: list[dict[str, Any]], results: Mapping[str, Any]
) -> dict[str, dict[str, Any]]:
    terminal: dict[str, dict[str, Any]] = {}
    for row in rows:
        dataset_id = str(row.get("dataset_id") or "")
        status = str(row.get("quality_status") or "").upper()
        result = results.get(dataset_id)
        if (
            dataset_id
            and status in TERMINAL
            and isinstance(result, Mapping)
            and result.get("verified_from_release") is True
            and result.get("replay_compatible") is not True
            and result.get("verifier_version") == VERIFIER_VERSION
            and result.get("asset_sha256") == row.get("sha256")
            and result.get("asset_size") == row.get("bytes")
            and str(result.get("quality_status_after") or "").upper() == status
            and _physical_key(row) is not None
        ):
            terminal[dataset_id] = row
    return terminal


def prepare(limit: int) -> dict[str, Any]:
    if PLAN.is_file():
        current = _load(PLAN)
        if current.get("status") == "READY" and current.get("plan_digest") == _digest(current):
            return current
    _, rows, source_sha = _verified_snapshot()
    patch = _load(PATCH)
    results = patch.get("results")
    if not isinstance(results, Mapping):
        raise Refuse("DELETION_REPAIR_RESULTS_INVALID")
    terminal = _terminal_rows(rows, results)
    grouped: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        key = _physical_key(row)
        if key is not None:
            grouped[key].append(row)

    selected: list[dict[str, Any]] = []
    for (tag, name), physical_rows in sorted(grouped.items()):
        # Deleting a physical asset is legal only when every logical member is
        # terminal. This protects SAFE and still-repairable members in ZIPs.
        if not physical_rows or any(str(row.get("dataset_id")) not in terminal for row in physical_rows):
            continue
        proof_sizes = {
            int(row.get("release_remote_size") or row.get("bytes") or 0)
            for row in physical_rows
        }
        proof_digests = {
            str(row.get("release_remote_digest") or ("sha256:" + str(row.get("sha256") or "")))
            for row in physical_rows
        }
        if len(proof_sizes) != 1 or len(proof_digests) != 1:
            continue
        remote = assets(release(tag)).get(name)
        if remote is None:
            continue
        expected_size = next(iter(proof_sizes))
        expected_digest = next(iter(proof_digests))
        if remote.get("size") != expected_size or remote.get("digest") != expected_digest:
            continue
        selected.append({
            "release_tag": tag,
            "asset_name": name,
            "asset_id": remote["id"],
            "remote_size": expected_size,
            "remote_digest": expected_digest,
            "datasets": [
                {
                    "dataset_id": row["dataset_id"],
                    "sha256": row["sha256"],
                    "bytes": row["bytes"],
                    "quality_status": row["quality_status"],
                    "manifest_path": row.get("manifest_path"),
                    "terminal_reason": results[row["dataset_id"]].get("replay_reason"),
                }
                for row in sorted(physical_rows, key=lambda item: item["dataset_id"])
            ],
        })
        if len(selected) >= max(1, limit):
            break

    plan: dict[str, Any] = {
        "schema": "alina.dataset_deletion_plan.v1",
        "status": "READY" if selected else "NO_ELIGIBLE_ASSETS",
        "repository": REPOSITORY,
        "source_index_sha256": source_sha,
        "verifier_version": VERIFIER_VERSION,
        "github_run_id": os.getenv("GITHUB_RUN_ID"),
        "assets": selected,
        "asset_count": len(selected),
        "dataset_count": sum(len(item["datasets"]) for item in selected),
        "bytes_planned": sum(item["remote_size"] for item in selected),
        "safe_assets_selected": 0,
    }
    plan["plan_digest"] = _digest(plan)
    _write(PLAN, plan)
    return plan


def execute(expected_digest: str, receipt_path: Path) -> dict[str, Any]:
    plan = _load(PLAN)
    if (
        plan.get("status") != "READY"
        or plan.get("plan_digest") != expected_digest
        or _digest(plan) != expected_digest
        or plan.get("repository") != REPOSITORY
    ):
        raise Refuse("DELETION_PLAN_LEASE_MISMATCH")
    _, rows, source_sha = _verified_snapshot()
    by_id = {str(row.get("dataset_id") or ""): row for row in rows}
    for item in plan["assets"]:
        for frozen in item["datasets"]:
            current = by_id.get(frozen["dataset_id"])
            if current is None or any(current.get(key) != frozen.get(key) for key in (
                "sha256", "bytes", "quality_status", "manifest_path"
            )):
                raise Refuse("DELETION_DATASET_CHANGED")
            if current.get("quality_status") == "SAFE":
                raise Refuse("DELETION_SAFE_PROTECTED")
    # Index may advance only through unrelated catalog receipts. Every target
    # identity is rechecked above; the frozen index digest remains evidence.
    deleted: list[dict[str, Any]] = []
    for item in plan["assets"]:
        current_assets = assets(release(item["release_tag"]))
        remote = current_assets.get(item["asset_name"])
        if remote is not None:
            if not (
                remote.get("id") == item["asset_id"]
                and remote.get("size") == item["remote_size"]
                and remote.get("digest") == item["remote_digest"]
            ):
                raise Refuse("DELETION_REMOTE_ASSET_CHANGED")
            url = f"https://api.github.com/repos/{REPOSITORY}/releases/assets/{item['asset_id']}"
            with request(url, method="DELETE") as response:
                if response.status != 204:
                    raise Refuse("DELETION_GITHUB_NOT_CONFIRMED")
        deleted.append(item)
    receipt = {
        "schema": "alina.dataset_deletion_receipt.v1",
        "status": "ASSETS_DELETED",
        "plan_digest": expected_digest,
        "planned_index_sha256": plan["source_index_sha256"],
        "executed_index_sha256": source_sha,
        "github_run_id": os.getenv("GITHUB_RUN_ID"),
        "assets": deleted,
        "asset_count": len(deleted),
        "dataset_count": sum(len(item["datasets"]) for item in deleted),
        "bytes_deleted": sum(item["remote_size"] for item in deleted),
    }
    _write(receipt_path, receipt)
    return receipt


def _remove_terminal_receipt(root: Path, manifest_path: str) -> bool:
    """Unindex verified terminal shards without rewriting huge legacy Git trees.

    When an old flat receipt directory is oversized, the obsolete receipt is
    preserved as non-admissible history; replay selectors trust only the index.
    """
    relative = Path(manifest_path)
    if (
        relative.is_absolute()
        or len(relative.parts) < 3
        or relative.parts[0] != "datasets"
        or any(part in (".", "..") for part in relative.parts)
    ):
        raise Refuse("DELETION_UNSAFE_MANIFEST_PATH")
    stage = relative.parts[1]
    if stage not in ("safe", "quarantine", "rejected", "sharded"):
        raise Refuse("DELETION_UNKNOWN_RECEIPT_STAGE")
    target = root / relative
    if target.is_symlink() or not target.resolve().is_relative_to(
        (root / "datasets").resolve()
    ):
        raise Refuse("DELETION_UNSAFE_RECEIPT_TARGET")
    # Touching even one historical flat entry would reconstruct the enormous
    # Git tree that caused the reconciliation publication failure.
    if len(relative.parts) == 3 and _oversized_legacy_stage(root, stage):
        return False
    if target.is_file():
        target.unlink()
        return True
    return False


def finalize(receipt_path: Path) -> dict[str, Any]:
    receipt = _load(receipt_path)
    plan = _load(PLAN)
    if (
        receipt.get("status") != "ASSETS_DELETED"
        or receipt.get("plan_digest") != plan.get("plan_digest")
        or _digest(plan) != plan.get("plan_digest")
    ):
        raise Refuse("DELETION_RECEIPT_PLAN_MISMATCH")
    index, rows, _ = _verified_snapshot()
    frozen = {
        item["dataset_id"]: item
        for asset in receipt.get("assets") or []
        for item in asset.get("datasets") or []
    }
    kept: list[dict[str, Any]] = []
    removed: list[dict[str, Any]] = []
    for row in rows:
        expected = frozen.get(str(row.get("dataset_id") or ""))
        if expected is None:
            kept.append(row)
            continue
        if row.get("quality_status") == "SAFE" or any(
            row.get(key) != expected.get(key)
            for key in ("sha256", "bytes", "quality_status", "manifest_path")
        ):
            raise Refuse("DELETION_FINALIZE_TARGET_CHANGED")
        _remove_terminal_receipt(ROOT, str(row.get("manifest_path") or ""))
        removed.append(expected)
    if len(removed) != len(frozen):
        raise Refuse("DELETION_FINALIZE_INCOMPLETE")
    index["shards"] = kept
    _refresh_catalog(index, ROOT)
    history = _load(HISTORY) if HISTORY.is_file() else {
        "schema": "alina.dataset_deletion_history.v1", "entries": []
    }
    history.setdefault("entries", []).append({
        "plan_digest": receipt["plan_digest"],
        "github_run_id": receipt.get("github_run_id"),
        "asset_count": receipt["asset_count"],
        "dataset_count": receipt["dataset_count"],
        "bytes_deleted": receipt["bytes_deleted"],
        "datasets": removed,
    })
    _write(HISTORY, history)
    completed = {**plan, "status": "COMPLETED", "receipt": {
        "asset_count": receipt["asset_count"],
        "dataset_count": receipt["dataset_count"],
        "bytes_deleted": receipt["bytes_deleted"],
    }}
    completed["plan_digest"] = _digest(completed)
    _write(PLAN, completed)
    return completed


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    prep = sub.add_parser("prepare")
    prep.add_argument("--limit", type=int, default=20)
    run = sub.add_parser("execute")
    run.add_argument("--expected-plan-digest", required=True)
    run.add_argument("--receipt", required=True)
    finish = sub.add_parser("finalize")
    finish.add_argument("--receipt", required=True)
    args = parser.parse_args()
    try:
        if args.command == "prepare":
            result = prepare(args.limit)
        elif args.command == "execute":
            result = execute(args.expected_plan_digest, Path(args.receipt))
        else:
            result = finalize(Path(args.receipt))
        print(json.dumps(result, indent=2, sort_keys=True))
        return 0
    except (OSError, ValueError, TypeError, KeyError, Refuse) as exc:
        print(json.dumps({"status": "DELETE_REFUSED_FAIL_CLOSED", "reason": str(exc)}))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
