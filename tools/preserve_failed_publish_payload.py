#!/usr/bin/env python3
"""Cloud-only bounded quarantine fallback when a completed collection cannot publish.

The fallback keeps only the publisher's own locally replay-admissible candidates.
Neither this temporary artifact nor its SHA permits SAFE promotion or backtests.
It is NOT part of the durable dataset catalog and expires after seven days.
"""
from __future__ import annotations

import argparse
import hashlib
import io
import json
import os
import re
import tarfile
import tempfile
from pathlib import Path, PurePosixPath
from typing import Any

try:
    from tools.publish_dataset_v2_release import partition_manifest_entries
except ModuleNotFoundError:
    from publish_dataset_v2_release import partition_manifest_entries

SHA256 = re.compile(r"[0-9a-f]{64}\Z")
MAX_BYTES = 128 * 1024 * 1024


def _file(root: Path, relative: str) -> Path:
    logical = PurePosixPath(relative)
    if (not relative or logical.is_absolute() or "\\" in relative
            or any(part in {"", ".", ".."} for part in logical.parts)):
        raise ValueError("QUARANTINE_UNSAFE_PATH")
    target = root.joinpath(*logical.parts)
    if (target.is_symlink() or not target.is_file()
            or not target.resolve().is_relative_to(root)):
        raise ValueError("QUARANTINE_SOURCE_MISSING_OR_UNSAFE")
    if any(parent.is_symlink() for parent in target.parents if parent != root):
        raise ValueError("QUARANTINE_SOURCE_SYMLINK")
    return target


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for part in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(part)
    return h.hexdigest()


def preserve(result_path: Path, output: Path, *, max_bytes: int = MAX_BYTES) -> dict[str, Any]:
    if type(max_bytes) is not int or max_bytes <= 0 or max_bytes > MAX_BYTES:
        raise ValueError("QUARANTINE_INVALID_BUDGET")
    result = json.loads(result_path.read_text(encoding="utf-8"))
    if not isinstance(result, dict) or result.get("status") != "COMPLETE":
        return {"status": "NOT_A_COMPLETED_COLLECTION"}
    bundle = (result.get("payload") or {}).get("bundle_root")
    if not isinstance(bundle, str) or not bundle:
        raise ValueError("QUARANTINE_MISSING_BUNDLE")
    root = Path(bundle).resolve(strict=True)
    index = json.loads(_file(root, "BUNDLE_INDEX.json").read_text(encoding="utf-8"))
    refs = index.get("manifests") if isinstance(index, dict) else None
    if not isinstance(refs, list) or not all(isinstance(x, str) for x in refs):
        raise ValueError("QUARANTINE_MISSING_MANIFEST_LIST")
    manifest_paths = [_file(root, ref) for ref in refs]
    manifests = [json.loads(p.read_text(encoding="utf-8")) for p in manifest_paths]
    if not all(isinstance(m, dict) for m in manifests):
        raise ValueError("QUARANTINE_INVALID_MANIFEST")
    eligible, rejected = partition_manifest_entries(manifest_paths, manifests)
    if not eligible:
        return {"status": "NO_LOCALLY_REPLAY_ADMISSIBLE_CANDIDATES", "excluded": len(rejected)}

    originals: list[tuple[Path, str]] = []
    assets_seen: dict[str, tuple[int, str]] = {}
    logical_bytes = 0
    preserved_rows: list[dict[str, Any]] = []
    preserved_manifest_paths: list[Path] = []
    skipped_budget = 0
    # Leave bounded room for the archive headers and the quarantine receipt.
    source_budget = max_bytes - min(2 * 1024 * 1024, max_bytes // 10)
    for manifest_path, row in eligible:
        member = row.get("release_asset")
        expected_sha = str(row.get("sha256") or "").lower()
        expected_size = row.get("bytes")
        if (not isinstance(member, str) or not member or PurePosixPath(member).name != member
                or type(expected_size) is not int or expected_size <= 0
                or SHA256.fullmatch(expected_sha) is None):
            raise ValueError("QUARANTINE_INVALID_ASSET_IDENTITY")
        identity = (expected_size, expected_sha)
        if member in assets_seen and assets_seen[member] != identity:
            raise ValueError("QUARANTINE_ASSET_IDENTITY_CONFLICT")
        asset = _file(root, "assets/" + member)
        manifest_size = manifest_path.stat().st_size
        new_asset_size = 0 if member in assets_seen else expected_size
        if logical_bytes + manifest_size + new_asset_size > source_budget:
            skipped_budget += 1
            continue
        if asset.stat().st_size != expected_size or _sha256(asset) != expected_sha:
            raise ValueError("QUARANTINE_ASSET_SHA_MISMATCH")
        if member not in assets_seen:
            assets_seen[member] = identity
            logical_bytes += expected_size
            originals.append((asset, "assets/" + member))
        manifest_relative = manifest_path.relative_to(root).as_posix()
        originals.append((manifest_path, manifest_relative))
        logical_bytes += manifest_size
        preserved_rows.append(row)
        preserved_manifest_paths.append(manifest_path)

    if not preserved_rows:
        return {
            "status": "QUARANTINE_SKIPPED_BUDGET",
            "max_bytes": max_bytes,
            "candidate_shards": len(eligible),
            "excluded": len(rejected),
            "omitted_due_budget": skipped_budget,
        }
    filtered_index = {
        **index,
        "manifests": [p.relative_to(root).as_posix() for p in preserved_manifest_paths],
        "assets": ["assets/" + name for name in sorted(assets_seen)],
        "shard_count": len(preserved_rows),
        "quarantine_only": True,
        "quarantine_source_complete": skipped_budget == 0,
        "safe_count": sum(row.get("quality_status") == "SAFE" for row in preserved_rows),
        "partial_count": sum(row.get("quality_status") == "PARTIAL" for row in preserved_rows),
        "reject_count": 0,
    }
    intent = {
        "schema": "alina.failed_publish_quarantine.v1",
        "status": "QUARANTINE_NOT_REPLAY_CERTIFIED",
        "source_run_status": "COMPLETE",
        "candidate_shards": len(preserved_rows),
        "source_candidate_shards": len(eligible),
        "omitted_due_budget": skipped_budget,
        "source_coverage_complete": skipped_budget == 0,
        "excluded_shards": len(rejected),
        "max_source_bytes": max_bytes,
        "source_bytes": logical_bytes,
        "paper_only": True,
        "read_only": True,
        "real_execution": False,
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    if output.is_symlink():
        raise ValueError("QUARANTINE_OUTPUT_SYMLINK")
    fd, name = tempfile.mkstemp(prefix=".alina-failed-publication-", suffix=".tgz",
                                dir=output.parent)
    os.close(fd)
    temporary = Path(name)
    try:
        with tarfile.open(temporary, "w:gz") as archive:
            for filename, payload in (
                ("BUNDLE_INDEX.json", filtered_index),
                ("QUARANTINE_INTENT.json", intent),
            ):
                data = (json.dumps(payload, sort_keys=True) + "\n").encode("utf-8")
                member = tarfile.TarInfo(filename)
                member.size = len(data)
                member.mode = 0o600
                archive.addfile(member, io.BytesIO(data))
            for path, relative in originals:
                archive.add(path, arcname=relative, recursive=False)
        if temporary.stat().st_size > max_bytes:
            return {
                "status": "QUARANTINE_SKIPPED_ARCHIVE_BUDGET",
                "archive_bytes": temporary.stat().st_size,
                "max_bytes": max_bytes,
            }
        size = temporary.stat().st_size
        digest = _sha256(temporary)
        temporary.replace(output)
        return {
            "status": "QUARANTINE_ARCHIVED",
            "candidate_shards": len(preserved_rows),
            "omitted_due_budget": skipped_budget,
            "source_coverage_complete": skipped_budget == 0,
            "excluded": len(rejected),
            "archive_bytes": size,
            "archive_sha256": digest,
            "replay_certified": False,
            "destination": str(output),
        }
    finally:
        temporary.unlink(missing_ok=True)


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--result", type=Path, required=True)
    p.add_argument("--output", type=Path, required=True)
    p.add_argument("--max-bytes", type=int, default=MAX_BYTES)
    args = p.parse_args()
    try:
        result = preserve(args.result, args.output, max_bytes=args.max_bytes)
    except (OSError, ValueError, TypeError, tarfile.TarError) as exc:
        print(json.dumps({"status": "QUARANTINE_FAIL_CLOSED", "reason": str(exc)}))
        return 2
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
