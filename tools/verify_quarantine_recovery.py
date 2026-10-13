#!/usr/bin/env python3
"""SHA-256 coverage audit of quarantined recovered shards; never replay approval."""
from __future__ import annotations

import argparse
import hashlib
import json
import re
from collections import Counter
from pathlib import Path
from typing import Any, Mapping

try:
    from tools.partitioned_data_index import read_index
    from tools.preservation_inventory import InventoryError, iter_recovery_triage, summarize
    from tools.restore_alina import _safe_component, _sha256
    from tools.recover_one_quarantined_shard import candidate_from_index, immutable_candidate_sha256
except ModuleNotFoundError:
    from partitioned_data_index import read_index
    from preservation_inventory import InventoryError, iter_recovery_triage, summarize
    from restore_alina import _safe_component, _sha256
    from recover_one_quarantined_shard import candidate_from_index, immutable_candidate_sha256

SHA = re.compile(r"[0-9a-f]{64}\Z")
CANONICAL = "Rapt0r06300/hyperliquid-smart-wallet-observer"


def verify_quarantine(root: Path, index: Mapping[str, Any], index_sha: str) -> dict[str, Any]:
    root = Path(root)
    if root.is_symlink() or not root.is_dir() or not SHA.fullmatch(index_sha):
        raise InventoryError("RECOVERY_COVERAGE_UNSAFE_SOURCE")
    rows = index["shards"]
    by_id = {row["dataset_id"]: row for row in rows}
    if len(by_id) != len(rows):
        raise InventoryError("RECOVERY_COVERAGE_DUPLICATE_INDEX_ID")
    unresolved = {c["dataset_id"] for c in iter_recovery_triage(index)}
    if len(unresolved) != sum(1 for _ in iter_recovery_triage(index)):
        raise InventoryError("RECOVERY_COVERAGE_DUPLICATE_CANDIDATE")
    directory = root / "quarantine" / "source_verified_non_replay"
    if directory.is_symlink():
        raise InventoryError("RECOVERY_COVERAGE_UNSAFE_QUARANTINE")
    receipts = sorted(directory.glob("*.receipt.json")) if directory.is_dir() else []
    seen = set()
    outer_cache: dict[tuple[str, str], tuple[int, str]] = {}
    verified_outer_assets: set[tuple[str, str]] = set()
    verified = 0
    verified_bytes = 0
    unchanged_shards_across_catalog_updates = 0
    invalid = Counter()
    samples = []
    for receipt_path in receipts:
        ident = receipt_path.name
        try:
            if receipt_path.is_symlink():
                raise ValueError("UNSAFE_RECEIPT_SYMLINK")
            receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
            ident = receipt.get("dataset_id")
            if not isinstance(ident, str) or not ident or ident in seen:
                raise ValueError("DUPLICATE_OR_INVALID_RECEIPT_ID")
            seen.add(ident)
            row = by_id.get(ident)
            if row is None or ident not in unresolved:
                raise ValueError("UNKNOWN_OR_ALREADY_REPLAY_READY_SHARD")
            snapshot_sha = receipt.get("catalog_index_sha256")
            if not isinstance(snapshot_sha, str) or not SHA.fullmatch(snapshot_sha):
                raise ValueError("INVALID_OR_MISSING_ORIGINAL_CATALOG_SHA")
            binding = receipt.get("immutable_candidate_sha256")
            if binding is not None:
                expected_candidate = candidate_from_index(index, ident)
                expected_binding = immutable_candidate_sha256(expected_candidate)
                if not isinstance(binding, str) or binding != expected_binding:
                    raise ValueError("IMMUTABLE_CANDIDATE_PROVENANCE_CHANGED")
            elif snapshot_sha != index_sha:
                # Legacy receipts have only the original whole-catalog SHA.
                # They cannot be safely rebound when that catalog changes.
                raise ValueError("STALE_CATALOG_PROOF_MISSING_ROW_BINDING")
            if receipt.get("original_quality_status") != row.get("quality_status"):
                raise ValueError("STALE_CATALOG_QUALITY_CHANGED")
            if (receipt.get("status") != "BYTE_VERIFIED_QUARANTINED_NOT_REPLAY_CERTIFIED"
                    or receipt.get("validation_allowed") is not False
                    or receipt.get("replay_certified") is not False
                    or receipt.get("reclassified_safe") is not False
                    or receipt.get("source_repository") != CANONICAL
                    or type(receipt.get("source_asset_id")) is not int
                    or receipt["source_asset_id"] <= 0):
                raise ValueError("UNSAFE_QUARANTINE_RECEIPT")
            logical_sha = row.get("sha256")
            logical_bytes = row.get("bytes")
            if (receipt.get("logical_sha256") != logical_sha
                    or receipt.get("logical_bytes") != logical_bytes
                    or type(logical_bytes) is not int or logical_bytes < 0
                    or not isinstance(logical_sha, str) or not SHA.fullmatch(logical_sha)):
                raise ValueError("SHARD_IDENTITY_MISMATCH")
            tag = row.get("release_tag")
            outer_name = row.get("release_container_asset") or row.get("release_asset")
            remote_size = row.get("release_remote_size") if row.get("release_container_asset") else logical_bytes
            remote_digest = row.get("release_remote_digest") if row.get("release_container_asset") else logical_sha
            remote_digest = remote_digest.removeprefix("sha256:").lower() if isinstance(remote_digest, str) else None
            if (receipt.get("release_tag") != tag
                    or receipt.get("outer_asset") != outer_name
                    or receipt.get("outer_bytes") != remote_size
                    or receipt.get("outer_sha256") != remote_digest):
                raise ValueError("OUTER_CATALOG_IDENTITY_MISMATCH")
            name = _safe_component(ident) + "." + logical_sha[:16] + ".jsonl.gz"
            recovered = directory / name
            if (receipt.get("quarantine_file") != str(recovered.relative_to(root)).replace("\\", "/")
                    or recovered.is_symlink() or not recovered.is_file()):
                raise ValueError("MISSING_OR_UNSAFE_SHARD")
            if recovered.stat().st_size != logical_bytes or _sha256(recovered) != logical_sha:
                raise ValueError("QUARANTINE_BYTES_CORRUPT")
            parent = root / "releases" / _safe_component(tag)
            outer = parent / _safe_component(outer_name)
            if ((root / "releases").is_symlink() or parent.is_symlink()
                    or outer.is_symlink() or not outer.is_file()):
                raise ValueError("MISSING_OR_UNSAFE_SOURCE_ASSET")
            key = (tag, outer_name)
            if key not in outer_cache:
                outer_cache[key] = (outer.stat().st_size, _sha256(outer))
            if outer_cache[key] != (remote_size, remote_digest):
                raise ValueError("SOURCE_ASSET_BYTES_CORRUPT")
            verified_outer_assets.add(key)
            verified += 1
            verified_bytes += logical_bytes
            if snapshot_sha != index_sha:
                unchanged_shards_across_catalog_updates += 1
        except (OSError, ValueError, TypeError, KeyError, UnicodeError) as error:
            invalid[type(error).__name__ + ":" + str(error)[:120]] += 1
            if len(samples) < 20:
                samples.append({"dataset_id": str(ident), "reason": str(error)})
    complete = verified == len(unresolved) and not invalid
    return {
        "schema": "alina.quarantine_byte_coverage.v1",
        "status": "BYTE_COVERAGE_COMPLETE_NOT_REPLAY_CERTIFIED" if complete
                  else "BYTE_COVERAGE_PARTIAL_OR_UNVERIFIED",
        "catalog_index_sha256": index_sha,
        "unresolved_catalog_shards": len(unresolved),
        "receipts_found": len(receipts),
        "byte_verified_non_safe_shards": verified,
        "byte_verified_after_unrelated_catalog_updates": unchanged_shards_across_catalog_updates,
        "unresolved_without_current_byte_proof": len(unresolved) - verified,
        "quarantined_logical_compressed_bytes_verified": verified_bytes,
        "unique_source_assets_verified": len(verified_outer_assets),
        "unique_source_assets_checked": len(outer_cache),
        "invalid_or_stale_receipts": sum(invalid.values()),
        "invalid_reason_counts": dict(sorted(invalid.items())),
        "invalid_sample": samples,
        "byte_coverage_complete": complete,
        "replay_certified": False,
        "reclassified_safe": False,
        "all_exploitable_data_restored": False,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--index", type=Path, default=Path("catalog/DATA_INDEX.json"))
    parser.add_argument("--metrics", type=Path, default=Path("catalog/DATA_METRICS.json"))
    parser.add_argument("--destination", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        raw = args.index.read_bytes()
        index = read_index(args.index)
        metrics = json.loads(args.metrics.read_text(encoding="utf-8"))
        summarize(index, metrics, hashlib.sha256(raw).hexdigest())
        result = verify_quarantine(args.destination, index, hashlib.sha256(raw).hexdigest())
        print(json.dumps(result, indent=2, sort_keys=True))
        return 2 if result["invalid_or_stale_receipts"] else 0
    except (OSError, ValueError, TypeError, UnicodeError, EOFError) as error:
        print(json.dumps({"status": "RECOVERY_COVERAGE_INCOMPLETE", "reason": str(error)}, sort_keys=True))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
