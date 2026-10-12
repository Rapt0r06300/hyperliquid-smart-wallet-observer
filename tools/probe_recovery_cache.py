#!/usr/bin/env python3
"""Bounded, read-only byte proof for *cached* non-SAFE recovery candidates.

Never downloads, deletes, promotes, repairs, or labels anything replay-ready.
Outer Release SHA/size AND the exact inner shard SHA/size must both match.
An absent cache means NOT TESTED, not unrecoverable.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import zipfile
from collections import Counter
from pathlib import Path
from typing import Any, Mapping

try:
    from tools.partitioned_data_index import read_index
    from tools.preservation_inventory import InventoryError, iter_recovery_triage, summarize
    from tools.restore_alina import _safe_component, _sha256
except ModuleNotFoundError:
    from partitioned_data_index import read_index
    from preservation_inventory import InventoryError, iter_recovery_triage, summarize
    from restore_alina import _safe_component, _sha256

REPO = Path(__file__).resolve().parents[1]
SHA = re.compile(r"[0-9a-f]{64}\Z")


def probe_cache(
    index: Mapping[str, Any], releases_root: Path, *,
    max_candidates: int = 200, max_verify_bytes: int = 1_000_000_000,
) -> dict[str, Any]:
    if type(max_candidates) is not int or max_candidates < 1:
        raise InventoryError("CACHE_PROBE_INVALID_CANDIDATE_LIMIT")
    if type(max_verify_bytes) is not int or max_verify_bytes < 1:
        raise InventoryError("CACHE_PROBE_INVALID_BYTE_BUDGET")
    root = Path(releases_root)
    if root.is_symlink() or not root.is_dir():
        raise InventoryError("CACHE_PROBE_MISSING_OR_SYMLINKED_ROOT")
    original = {r["dataset_id"]: r for r in index["shards"]}
    if len(original) != len(index["shards"]):
        raise InventoryError("CACHE_PROBE_DUPLICATE_SHARD_IDS")
    stats: Counter[str] = Counter()
    found: list[dict[str, Any]] = []
    checked: dict[tuple[str, str], str] = {}
    used = 0
    seen = 0
    for candidate in iter_recovery_triage(index):
        if seen >= max_candidates:
            break
        seen += 1
        dataset_id = candidate["dataset_id"]
        row = original[dataset_id]
        tag, member = candidate.get("release_tag"), candidate.get("release_asset")
        container = row.get("release_container_asset")
        packed = bool(container)
        outer_name = container if packed else member
        expected_inner_sha = row.get("sha256")
        inner_size = row.get("bytes")
        expected_outer_size = row.get("release_remote_size") if packed else inner_size
        outer_digest = row.get("release_remote_digest") if packed else expected_inner_sha
        outer_sha = outer_digest.removeprefix("sha256:").lower() if isinstance(outer_digest, str) else None
        inner_sha = expected_inner_sha.lower() if isinstance(expected_inner_sha, str) else None
        reason = "INDEX_IDENTITY_INCOMPLETE"
        if (
            isinstance(tag, str) and tag
            and isinstance(outer_name, str) and outer_name
            and isinstance(member, str) and member
            and Path(member).name == member
            and type(inner_size) is int and inner_size >= 0
            and type(expected_outer_size) is int and expected_outer_size >= 0
            and isinstance(inner_sha, str) and SHA.fullmatch(inner_sha)
            and isinstance(outer_sha, str) and SHA.fullmatch(outer_sha)
            and "canonical_release_repository" not in candidate["missing_evidence"]
        ):
            directory = root / _safe_component(tag)
            path = directory / _safe_component(outer_name)
            if directory.is_symlink() or path.is_symlink():
                reason = "UNSAFE_SYMLINK"
            elif not path.is_file():
                reason = "SOURCE_NOT_CACHED"
            elif path.stat().st_size != expected_outer_size:
                reason = "SOURCE_OUTER_SIZE_MISMATCH"
            else:
                key = (tag, outer_name)
                if key not in checked:
                    if used + expected_outer_size > max_verify_bytes:
                        reason = "VERIFY_BYTE_BUDGET_EXCEEDED"
                    else:
                        used += expected_outer_size
                        checked[key] = (
                            "SOURCE_OUTER_VERIFIED" if _sha256(path) == outer_sha
                            else "SOURCE_OUTER_SHA_MISMATCH"
                        )
                if key in checked:
                    reason = checked[key]
                    if reason == "SOURCE_OUTER_VERIFIED":
                        if not packed:
                            reason = (
                                "BYTE_VERIFIED_NON_SAFE_NOT_REPLAY_CERTIFIED"
                                if outer_sha == inner_sha and expected_outer_size == inner_size
                                else "SHARD_BYTES_MISMATCH"
                            )
                        elif used + inner_size > max_verify_bytes:
                            reason = "VERIFY_BYTE_BUDGET_EXCEEDED"
                        else:
                            try:
                                with zipfile.ZipFile(path) as zf:
                                    matches = [info for info in zf.infolist()
                                               if info.filename == member]
                                    if len(matches) != 1:
                                        reason = "ZIP_MEMBER_MISSING_OR_DUPLICATE"
                                    elif matches[0].file_size != inner_size:
                                        reason = "SHARD_SIZE_MISMATCH"
                                    else:
                                        h = hashlib.sha256()
                                        length = 0
                                        with zf.open(matches[0]) as stream:
                                            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                                                length += len(chunk)
                                                h.update(chunk)
                                                if length > inner_size:
                                                    break
                                        used += length
                                        reason = (
                                            "BYTE_VERIFIED_NON_SAFE_NOT_REPLAY_CERTIFIED"
                                            if length == inner_size and h.hexdigest() == inner_sha
                                            else "SHARD_BYTES_MISMATCH"
                                        )
                            except (OSError, ValueError, EOFError, RuntimeError,
                                    zipfile.BadZipFile, zipfile.LargeZipFile):
                                reason = "ZIP_MEMBER_READ_ERROR"
        stats[reason] += 1
        found.append({
            "dataset_id": dataset_id, "quality_status": candidate["quality_status"],
            "source_check": reason, "validation_allowed": False,
        })
    total = sum(1 for _ in iter_recovery_triage(index))
    success = stats["BYTE_VERIFIED_NON_SAFE_NOT_REPLAY_CERTIFIED"]
    return {
        "schema": "alina.recovery_cache_probe.v1",
        "status": "CACHED_BYTES_PROBED_NOT_REPLAY_CERTIFIED",
        "candidates_total": total,
        "candidates_checked": seen,
        "candidates_not_checked": total - seen,
        "byte_budget": max_verify_bytes,
        "verification_bytes_read": used,
        "cached_shards_byte_verified": success,
        "source_check_counts": dict(sorted(stats.items())),
        "results": found,
        "repair_succeeded": False,
        "replay_certified": False,
        "all_exploitable_data_restored": False,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--index", type=Path, default=REPO / "catalog/DATA_INDEX.json")
    parser.add_argument("--metrics", type=Path, default=REPO / "catalog/DATA_METRICS.json")
    parser.add_argument("--releases-root", type=Path, required=True,
                        help="Existing local cache, e.g. runtime/recovery/full/releases")
    parser.add_argument("--max-candidates", type=int, default=200)
    parser.add_argument("--max-verify-bytes", type=int, default=1_000_000_000)
    args = parser.parse_args(argv)
    try:
        raw = args.index.read_bytes()
        index = read_index(args.index)
        metrics = json.loads(args.metrics.read_text(encoding="utf-8"))
        summarize(index, metrics, hashlib.sha256(raw).hexdigest())
        result = probe_cache(index, args.releases_root,
                             max_candidates=args.max_candidates,
                             max_verify_bytes=args.max_verify_bytes)
    except (OSError, ValueError, TypeError) as exc:
        print(json.dumps({"status": "CACHE_PROBE_INCOMPLETE", "reason": str(exc)}, sort_keys=True))
        return 2
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
