#!/usr/bin/env python3
"""Compute exact global unique trade counts without storing the identity universe in Git.

The previous implementation persisted every canonical trade identity in
TRADE_UNIQUE_COUNT_PATCH.json.  On real Dataset V2 volumes that file grows past
GitHub's 100 MiB blob limit, so otherwise-valid scans could never be published.
This implementation rescans the bounded trade-bearing immutable corpus, merges
full identities in a temporary SQLite store, and persists only compact per-shard
counts plus a deterministic digest.  Missing/unavailable shards remain explicit
and coverage stays fail-closed.
"""
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
import gzip
import hashlib
import json
import os
import shutil
import sqlite3
import tempfile
from pathlib import Path
from typing import Any, Mapping

try:
    from tools.backfill_exact_trade_counts import (
        TRADE_FAMILIES,
        _download,
        _native_trade_keys,
    )
except ModuleNotFoundError:
    from backfill_exact_trade_counts import TRADE_FAMILIES, _download, _native_trade_keys

ROOT = Path(__file__).resolve().parents[1]
INDEX_PATH = ROOT / "catalog" / "DATA_INDEX.json"
PATCH_PATH = ROOT / "catalog" / "TRADE_UNIQUE_COUNT_PATCH.json"
EXACT_COUNT_PATCH_PATH = ROOT / "catalog" / "TRADE_COUNT_PATCH.json"


def _persist_manifest_unique_counts(
    row: Mapping[str, Any],
    *,
    unique_count: int,
    exact: bool,
) -> None:
    manifest_path = ROOT / str(row.get("manifest_path") or "")
    if not manifest_path.is_file():
        return
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return
    if not isinstance(manifest, dict):
        return
    manifest["unique_trade_count"] = int(unique_count) if exact else None
    manifest["unique_trade_count_exact"] = bool(exact)
    temporary = manifest_path.with_suffix(manifest_path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    os.replace(temporary, manifest_path)


def _restore_exact_trade_count_rows(
    rows: list[Any],
    *,
    patch_path: Path | None = None,
) -> int:
    """Rehydrate SHA-matched exact trade counts before selecting unique-scan candidates.

    Replay qualification is a separate concern and must never be able to shrink
    the globally deduplicated trade universe by temporarily clearing
    trade_count_exact in DATA_INDEX.
    """
    path=patch_path or EXACT_COUNT_PATCH_PATH
    if not path.is_file():
        return 0
    try:
        doc=json.loads(path.read_text(encoding="utf-8"))
    except (OSError,ValueError,TypeError):
        return 0
    counts=doc.get("counts") if isinstance(doc,Mapping) else {}
    if not isinstance(counts,Mapping):
        return 0

    restored=0
    for row in rows:
        if not isinstance(row,dict):
            continue
        dataset_id=str(row.get("dataset_id") or "")
        family=str(row.get("family") or "").lower()
        if not dataset_id or family not in TRADE_FAMILIES:
            continue
        evidence=counts.get(dataset_id)
        if not isinstance(evidence,Mapping) or evidence.get("trade_count_exact") is not True:
            continue
        row_sha=str(row.get("sha256") or "").lower()
        evidence_sha=str(evidence.get("asset_sha256") or "").lower()
        if len(row_sha)!=64 or evidence_sha!=row_sha:
            continue
        try:
            count=int(evidence.get("trade_count"))
        except (TypeError,ValueError,OverflowError):
            continue
        if count<0:
            continue
        if row.get("trade_count_exact") is not True or row.get("trade_count")!=count:
            restored+=1
        row["trade_count"]=count
        row["trade_count_exact"]=True
    return restored


def _positive_int(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    try:
        parsed = int(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return parsed if parsed > 0 else None


def _unique_candidate(row: Mapping[str, Any]) -> bool:
    """Return True only for immutable shards that actually carry trades."""
    dataset_id = str(row.get("dataset_id") or "")
    family = str(row.get("family") or "").lower()
    if not dataset_id or family not in TRADE_FAMILIES:
        return False
    if row.get("trade_count_exact") is not True:
        return False
    if _positive_int(row.get("trade_count")) is None:
        return False
    return bool(
        row.get("release_repository")
        and row.get("release_tag")
        and row.get("release_asset")
        and row.get("sha256")
        and row.get("bytes")
    )


def canonical_identity(value: str) -> str:
    """Use the complete canonical identity; hashes are evidence digests only."""
    if not isinstance(value, str) or not value:
        raise ValueError("empty trade identity")
    return value


def _scan_candidate(row: Mapping[str, Any], temporary_root: Path) -> dict[str, Any]:
    """Download one immutable trade shard and persist only its local identity set."""
    dataset_id = str(row.get("dataset_id") or "")
    shard_root = temporary_root / dataset_id
    shard_root.mkdir(parents=True, exist_ok=True)
    asset = _download(row, shard_root)
    total = 0
    exact = True
    shard_ids: set[str] = set()
    with gzip.open(asset, "rt", encoding="utf-8") as handle:
        for line in handle:
            if not line.strip():
                continue
            raw = json.loads(line)
            if not isinstance(raw, Mapping):
                continue
            keys = _native_trade_keys(
                raw,
                venue=str(row.get("venue") or "unknown"),
                family=str(row.get("family") or ""),
                symbol=str(row.get("symbol") or ""),
            )
            if keys is None:
                exact = False
                continue
            total += len(keys)
            shard_ids.update(canonical_identity(key) for key in keys)

    identity_path = shard_root / "identities.txt"
    if exact:
        with identity_path.open("w", encoding="utf-8", newline="\n") as handle:
            for identity in sorted(shard_ids):
                handle.write(identity)
                handle.write("\n")

    # The downloaded release asset is no longer needed after deterministic parsing.
    try:
        asset.unlink()
    except OSError:
        pass

    return {
        "dataset_id": dataset_id,
        "trade_count_scanned": total,
        "unique_trade_count": len(shard_ids),
        "identity_path": str(identity_path),
        "exact": exact,
    }


def _digest_sqlite_identities(database: sqlite3.Connection) -> str:
    digest = hashlib.sha256()
    for (identity,) in database.execute("SELECT identity FROM ids ORDER BY identity"):
        digest.update(str(identity).encode("utf-8"))
        digest.update(b"\n")
    return digest.hexdigest()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=5000)
    parser.add_argument("--workers", type=int, default=16)
    args = parser.parse_args()
    if args.limit < 1:
        raise SystemExit("limit must be positive")
    if not 1 <= args.workers <= 32:
        raise SystemExit("workers must be between 1 and 32")

    index = json.loads(INDEX_PATH.read_text(encoding="utf-8"))
    rows = index.get("shards")
    if not isinstance(rows, list):
        raise SystemExit("invalid DATA_INDEX shards")

    restored_exact_trade_rows=_restore_exact_trade_count_rows(rows)

    prior: dict[str, Any] = {}
    if PATCH_PATH.exists():
        try:
            prior = json.loads(PATCH_PATH.read_text(encoding="utf-8"))
        except (OSError, ValueError, TypeError):
            prior = {}
    failure_attempts = (
        prior.get("failure_attempts")
        if isinstance(prior, dict) and isinstance(prior.get("failure_attempts"), dict)
        else {}
    )

    trade_rows_in_scope = [
        row for row in rows
        if isinstance(row, Mapping)
        and str(row.get("family") or "").lower() in TRADE_FAMILIES
    ]
    unproven_trade_count_ids = sorted(
        str(row.get("dataset_id") or "")
        for row in trade_rows_in_scope
        if row.get("trade_count_exact") is not True
    )
    all_candidates = sorted(
        (
            row
            for row in trade_rows_in_scope
            if _unique_candidate(row)
        ),
        key=lambda row: str(row.get("dataset_id") or ""),
    )
    candidates = all_candidates[: args.limit]
    failed: list[dict[str, Any]] = []
    failure_reasons: dict[str, dict[str, Any]] = {}
    counts: dict[str, dict[str, Any]] = {}

    with tempfile.TemporaryDirectory(prefix="alina-global-unique-") as temporary:
        root = Path(temporary)
        scanned_by_id: dict[str, dict[str, Any] | Exception] = {}

        def scan(row: Mapping[str, Any]) -> tuple[str, dict[str, Any]]:
            result = _scan_candidate(row, root)
            return str(row.get("dataset_id") or ""), result

        with ThreadPoolExecutor(max_workers=args.workers) as pool:
            futures = {pool.submit(scan, row): row for row in candidates}
            for future in as_completed(futures):
                row = futures[future]
                dataset_id = str(row.get("dataset_id") or "")
                try:
                    _, result = future.result()
                    scanned_by_id[dataset_id] = result
                except Exception as exc:  # isolated shard failure; coverage stays false
                    scanned_by_id[dataset_id] = exc

        database = sqlite3.connect(root / "identities.sqlite")
        database.execute("CREATE TABLE ids (identity TEXT PRIMARY KEY)")
        database.execute("PRAGMA journal_mode=OFF")
        database.execute("PRAGMA synchronous=OFF")

        successful_ids: set[str] = set()
        for row in candidates:
            dataset_id = str(row.get("dataset_id") or "")
            scanned = scanned_by_id.get(dataset_id)
            if isinstance(scanned, Exception) or scanned is None:
                exc = scanned if isinstance(scanned, Exception) else RuntimeError("missing_scan_result")
                attempts = int(failure_attempts.get(dataset_id) or 0) + 1
                failure_attempts[dataset_id] = attempts
                failure = {
                    "dataset_id": dataset_id,
                    "reason": type(exc).__name__,
                    "detail": str(exc)[-500:],
                    "attempts": attempts,
                }
                failed.append(failure)
                failure_reasons[dataset_id] = failure
                continue
            if scanned.get("exact") is not True:
                attempts = int(failure_attempts.get(dataset_id) or 0) + 1
                failure_attempts[dataset_id] = attempts
                failure = {
                    "dataset_id": dataset_id,
                    "reason": "identity_missing",
                    "attempts": attempts,
                }
                failed.append(failure)
                failure_reasons[dataset_id] = failure
                continue

            global_new = 0
            identity_path = Path(str(scanned["identity_path"]))
            with identity_path.open("r", encoding="utf-8") as handle:
                for line in handle:
                    identity = canonical_identity(line.rstrip("\n"))
                    before = database.total_changes
                    database.execute(
                        "INSERT OR IGNORE INTO ids(identity) VALUES (?)",
                        (identity,),
                    )
                    global_new += int(database.total_changes > before)
            database.commit()

            unique_count = int(scanned["unique_trade_count"])
            counts[dataset_id] = {
                "trade_count_scanned": int(scanned["trade_count_scanned"]),
                "unique_trade_count": unique_count,
                "unique_trade_count_exact": True,
                "global_new_identity_count": global_new,
                "cross_shard_overlap_count": max(0, unique_count - global_new),
                "identity_version": "native-id-or-venue-family-symbol-time-side-price-size-v3-full-string",
            }
            _persist_manifest_unique_counts(
                row,
                unique_count=unique_count,
                exact=True,
            )
            successful_ids.add(dataset_id)
            failure_attempts.pop(dataset_id, None)

        observed_global_count = int(
            database.execute("SELECT COUNT(*) FROM ids").fetchone()[0]
        )
        observed_identity_digest = _digest_sqlite_identities(database)
        database.close()

    for row in rows:
        if isinstance(row, dict):
            patch_row = counts.get(str(row.get("dataset_id") or ""))
            if isinstance(patch_row, Mapping):
                row.update(patch_row)
    INDEX_PATH.write_text(
        json.dumps(index, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
    )

    all_candidate_ids = {
        str(row.get("dataset_id") or "") for row in all_candidates
    }
    remaining_ids = sorted(all_candidate_ids - successful_ids)
    unscanned_count = max(0, len(all_candidates) - len(candidates))
    coverage_complete = (
        not unproven_trade_count_ids
        and not remaining_ids
        and not failed
        and unscanned_count == 0
    )
    cross_shard_overlap_count = sum(
        int(value.get("cross_shard_overlap_count") or 0)
        for value in counts.values()
        if isinstance(value, Mapping)
    )

    result = {
        "schema": "alina.global_unique_trade_patch.v4",
        "method": "full_trade_corpus_parallel_scan_then_deterministic_sqlite_merge",
        "identity_version": "native-id-or-venue-family-symbol-time-side-price-size-v3-full-string",
        "collision_policy": (
            "full canonical identity strings; native identifiers preferred; "
            "ambiguous missing identities fail closed"
        ),
        "trade_shards_in_scope": len(trade_rows_in_scope),
        "unproven_trade_count_shards": len(unproven_trade_count_ids),
        "unproven_trade_count_dataset_ids": unproven_trade_count_ids,
        "candidate_trade_shards": len(all_candidates),
        "restored_exact_trade_rows": restored_exact_trade_rows,
        "attempted": len(candidates),
        "successful": len(successful_ids),
        "failed": failed,
        "failure_reasons": dict(sorted(failure_reasons.items())),
        "failure_attempts": dict(sorted(failure_attempts.items())),
        "counts": dict(sorted(counts.items())),
        "remaining_candidate_shards": len(remaining_ids),
        "unscanned_candidate_shards": unscanned_count,
        "observed_unique_trade_count": observed_global_count,
        "global_unique_trade_count": (
            observed_global_count if coverage_complete else None
        ),
        "observed_identity_digest": observed_identity_digest,
        "global_identity_digest": (
            observed_identity_digest if coverage_complete else None
        ),
        "cross_shard_overlap_count": cross_shard_overlap_count,
        "coverage_complete": coverage_complete,
        "identity_store_persisted": False,
        "identity_store_policy": (
            "identity universe is recomputed from immutable release assets; "
            "only compact counts and digest are persisted in Git"
        ),
    }
    PATCH_PATH.write_text(
        json.dumps(result, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
    )
    print(
        json.dumps(
            {
                key: result[key]
                for key in (
                    "trade_shards_in_scope",
                    "unproven_trade_count_shards",
                    "candidate_trade_shards",
                    "restored_exact_trade_rows",
                    "attempted",
                    "successful",
                    "remaining_candidate_shards",
                    "global_unique_trade_count",
                    "coverage_complete",
                )
            },
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
