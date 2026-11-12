#!/usr/bin/env python3
"""Merge slow verified size/record scans against the CURRENT GitHub main index.

Never replay an old Git commit over live catalog changes. The caller fetches
main and invokes this helper in a fresh GitHub-hosted checkout. Exact SHA-bound
evidence is kept, conflicting or stale evidence is refused.
"""
from __future__ import annotations

import argparse
import json
import os
import tempfile
from pathlib import Path
from typing import Any, Mapping

try:
    from tools.measured_catalog_patches import load_patch, write_patch
    from tools.partitioned_data_index import read_index
except ModuleNotFoundError:
    from measured_catalog_patches import load_patch, write_patch
    from partitioned_data_index import read_index

TABLES = (
    ("UNCOMPRESSED_SIZE_PATCH.json", "sizes", "alina.uncompressed_size_patch.v2"),
    ("RECORD_COUNT_PATCH.json", "records", "alina.record_count_patch.v1"),
)
MAX_PATCH_BYTES = 95_000_000


def _atomic_write_utf8(target: Path, payload: str) -> None:
    """Write a measured catalog without exposing a partial JSON document."""
    target.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(
        prefix=f".{target.name}.", suffix=".merge.tmp", dir=target.parent
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, target)
    finally:
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass


def _load(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"non-object patch: {path}")
    return value


def _exact(value: Any, kind: str, sha: str) -> bool:
    if not isinstance(value, Mapping):
        return False
    if str(value.get("asset_sha256") or "").lower() != sha:
        return False
    if kind == "sizes":
        return type(value.get("uncompressed_bytes")) is int and value["uncompressed_bytes"] >= 0
    return (
        value.get("exact") is True
        and type(value.get("record_count")) is int and value["record_count"] >= 0
        and type(value.get("valid_record_count")) is int
        and type(value.get("invalid_record_count")) is int
        and type(value.get("unique_record_count")) is int
        and value["valid_record_count"] >= 0
        and value["invalid_record_count"] >= 0
        and value["valid_record_count"] + value["invalid_record_count"] == value["record_count"]
        and 0 <= value["unique_record_count"] <= value["valid_record_count"]
    )


def merge_patch(
    current: Mapping[str, Any],
    measured: Mapping[str, Any],
    *,
    index_rows: list[Mapping[str, Any]],
    kind: str,
    schema: str,
) -> dict[str, Any]:
    """Carry forward full proof only for an unchanged indexed asset hash."""
    current_rows = current.get(kind, {})
    measured_rows = measured.get(kind, {})
    if not isinstance(current_rows, Mapping) or not isinstance(measured_rows, Mapping):
        raise ValueError("malformed size/record tables")
    result: dict[str, Any] = {}
    contradictions: list[str] = []
    for row in index_rows:
        dataset_id = row.get("dataset_id")
        sha = str(row.get("sha256") or "").lower()
        if not isinstance(dataset_id, str) or len(sha) != 64:
            raise ValueError("invalid indexed dataset or sha")
        old = current_rows.get(dataset_id)
        new = measured_rows.get(dataset_id)
        old_exact = _exact(old, kind, sha)
        new_exact = _exact(new, kind, sha)
        if old_exact and new_exact:
            fields = ("uncompressed_bytes",) if kind == "sizes" else (
                "record_count", "valid_record_count",
                "invalid_record_count", "unique_record_count",
            )
            if any(old[field] != new[field] for field in fields):
                contradictions.append(dataset_id)
                continue
        if old_exact:
            result[dataset_id] = dict(old)
        elif new_exact:
            result[dataset_id] = dict(new)
        else:
            # Old results for a different SHA must not be reused after an
            # immutable shard identity changed.
            compatible = [
                x for x in (old, new)
                if isinstance(x, Mapping)
                and (not x.get("asset_sha256") or x.get("asset_sha256") == sha)
            ]
            if compatible:
                # Genuine retryable unknowns stay retryable. Never confuse
                # "not scanned" with a proven successful scan.
                best = next(
                    (x for x in compatible if x.get("retryable") is not True),
                    compatible[-1],
                )
                result[dataset_id] = dict(best)
    if contradictions:
        raise ValueError("conflicting exact immutable evidence: " + ",".join(contradictions[:8]))

    # A structurally malformed or non-SHA-bound entry must never count as
    # covered merely because it is present in the patch dictionary. Only
    # exact verified evidence closes a row; terminal UNAVAILABLE remains
    # separately visible through unavailable_assets.
    unresolved = [
        row for row in index_rows
        if not _exact(
            result.get(row["dataset_id"]), kind, str(row["sha256"]).lower()
        ) and not (
            isinstance(result.get(row["dataset_id"]), Mapping)
            and result[row["dataset_id"]].get("status") == "UNAVAILABLE"
            and result[row["dataset_id"]].get("retryable") is not True
        )
    ]
    unavailable = sum(
        1 for value in result.values()
        if value.get("status") == "UNAVAILABLE" and value.get("retryable") is not True
    )
    exact = sum(
        _exact(result.get(row["dataset_id"]), kind, str(row["sha256"]).lower())
        for row in index_rows
    )
    merged = dict(current)
    merged["schema"] = schema
    merged["method"] = measured.get("method") or current.get("method") or "sha_bound_verified_merge"
    merged[kind] = dict(sorted(result.items()))
    merged["exact_assets"] = exact
    merged["unavailable_assets"] = unavailable
    merged["remaining_assets"] = len(unresolved)
    merged["coverage_complete"] = exact == len(index_rows) and unavailable == 0
    merged["attempted"] = measured.get("attempted", 0)
    merged["failed"] = [dict(id=row["dataset_id"], reason="MISSING_OR_RETRYABLE")
                        for row in unresolved[:100]]
    return merged


def merge_directory(measured_root: Path, repo_root: Path) -> dict[str, Any]:
    index = read_index(repo_root / "catalog" / "DATA_INDEX.json")
    rows = index.get("shards")
    if not isinstance(rows, list):
        raise ValueError("invalid active DATA_INDEX")
    out: dict[str, Any] = {}
    pending: list[tuple[Path, str]] = []
    for file_name, kind, schema in TABLES:
        target = repo_root / "catalog" / file_name
        measured = load_patch(measured_root / file_name, kind)
        if not measured:
            raise ValueError(f"missing freshly measured patch: {file_name}")
        updated = merge_patch(
            load_patch(target, kind), measured, index_rows=rows, kind=kind, schema=schema
        )
        # Validate BOTH complete products before replacing EITHER patch. The
        # writer partitions oversized exact evidence into bounded SHA-verified
        # parts and publishes the root last.
        pending.append((target, updated, kind))
        out[kind] = {
            "exact": updated["exact_assets"],
            "remaining": updated["remaining_assets"],
            "unavailable": updated["unavailable_assets"],
        }
    for target, updated, kind in pending:
        write_patch(target, updated, kind)
    return out


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--measured-root", type=Path, required=True)
    parser.add_argument("--repo-root", type=Path, default=Path.cwd())
    args = parser.parse_args()
    print(json.dumps(merge_directory(args.measured_root, args.repo_root), sort_keys=True))


if __name__ == "__main__":
    main()
