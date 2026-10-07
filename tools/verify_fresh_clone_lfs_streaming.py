#!/usr/bin/env python3
"""Stream-verify Git LFS payload bytes from a fresh clone.

The verifier is designed for GitHub-hosted runners that cannot hold the complete
Alina payload at once. It starts from a clone with LFS smudging disabled, fetches
bounded groups of LFS objects from the repository origin, verifies exact size and
SHA-256, deletes the verified local bytes, then continues.

Across all shards this proves every manifest object is remotely retrievable and
byte-identical without requiring ~200 GiB of runner disk at once.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
from collections.abc import Mapping
from pathlib import Path
from typing import Any

MANIFEST_PATH = Path("clone_payload/MANIFEST.json")
DEFAULT_BATCH_ASSETS = 250
DEFAULT_BATCH_BYTES = 700 * 1024 * 1024
POINTER_PREFIX = "version https://git-lfs.github.com/spec/v1"


class StreamingCloneError(RuntimeError):
    pass


def _run(
    args: list[str],
    *,
    cwd: Path,
    env: Mapping[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    merged = os.environ.copy()
    if env:
        merged.update(env)
    result = subprocess.run(
        args,
        cwd=cwd,
        env=merged,
        text=True,
        capture_output=True,
        encoding="utf-8",
        errors="replace",
    )
    if result.returncode != 0:
        detail = (result.stderr or result.stdout or "").strip()
        raise StreamingCloneError(f"{' '.join(args)} failed: {detail}")
    return result


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(8 * 1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_manifest(root: Path) -> dict[str, Any]:
    path = root / MANIFEST_PATH
    if not path.is_file():
        raise StreamingCloneError(f"missing clone payload manifest: {path}")
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise StreamingCloneError("invalid clone payload manifest JSON") from exc
    if not isinstance(payload, dict):
        raise StreamingCloneError("clone payload manifest is not an object")
    if payload.get("schema") != "alina.clone_payload_manifest.v1":
        raise StreamingCloneError("unsupported clone payload manifest schema")
    if not isinstance(payload.get("entries"), list):
        raise StreamingCloneError("clone payload manifest entries are missing")
    return payload


def safe_row(row: Mapping[str, Any], *, root: Path) -> dict[str, Any]:
    relative = str(row.get("clone_path") or "")
    expected_size = int(row.get("bytes") or -1)
    expected_sha = str(row.get("sha256") or "").lower()
    asset_id = int(row.get("asset_id") or 0)
    path = Path(relative)
    if (
        asset_id <= 0
        or not relative
        or path.is_absolute()
        or ".." in path.parts
        or "," in relative
        or expected_size < 0
        or len(expected_sha) != 64
        or any(ch not in "0123456789abcdef" for ch in expected_sha)
    ):
        raise StreamingCloneError(f"invalid clone manifest row for asset_id={asset_id}")
    resolved = (root / path).resolve()
    root_resolved = root.resolve()
    if resolved != root_resolved and root_resolved not in resolved.parents:
        raise StreamingCloneError(f"clone payload path escapes repository: {relative}")
    return {
        "asset_id": asset_id,
        "clone_path": relative,
        "bytes": expected_size,
        "sha256": expected_sha,
    }


def shard_rows(
    rows: list[Mapping[str, Any]],
    *,
    root: Path,
    shard_count: int,
    shard_index: int,
) -> list[dict[str, Any]]:
    if shard_count < 1 or shard_index < 0 or shard_index >= shard_count:
        raise StreamingCloneError("invalid shard coordinates")
    result: list[dict[str, Any]] = []
    for index, row in enumerate(rows):
        if not isinstance(row, Mapping):
            raise StreamingCloneError("invalid non-object manifest row")
        if index % shard_count == shard_index:
            result.append(safe_row(row, root=root))
    return result


def plan_batches(
    rows: list[dict[str, Any]],
    *,
    max_assets: int,
    max_bytes: int,
) -> list[list[dict[str, Any]]]:
    if max_assets < 1 or max_bytes < 1:
        raise StreamingCloneError("batch bounds must be positive")
    batches: list[list[dict[str, Any]]] = []
    current: list[dict[str, Any]] = []
    current_bytes = 0
    for row in rows:
        size = int(row["bytes"])
        if current and (
            len(current) >= max_assets or current_bytes + size > max_bytes
        ):
            batches.append(current)
            current = []
            current_bytes = 0
        current.append(row)
        current_bytes += size
        if len(current) >= max_assets:
            batches.append(current)
            current = []
            current_bytes = 0
    if current:
        batches.append(current)
    return batches


def parse_pointer(raw: str) -> tuple[str, int]:
    oid = ""
    size: int | None = None
    lines = raw.splitlines()
    if not lines or lines[0] != POINTER_PREFIX:
        raise StreamingCloneError("HEAD object is not a Git LFS pointer")
    for line in lines[1:]:
        if line.startswith("oid sha256:"):
            oid = line.split(":", 1)[1].strip().lower()
        elif line.startswith("size "):
            size = int(line.split()[1])
    if (
        len(oid) != 64
        or any(ch not in "0123456789abcdef" for ch in oid)
        or size is None
        or size < 0
    ):
        raise StreamingCloneError("invalid Git LFS pointer identity")
    return oid, size


def pointer_for_path(root: Path, relative: str) -> tuple[str, int]:
    raw = _run(["git", "show", f"HEAD:{relative}"], cwd=root).stdout
    return parse_pointer(raw)


def _lfs_object_path(root: Path, oid: str) -> Path:
    git_dir_raw = _run(["git", "rev-parse", "--git-dir"], cwd=root).stdout.strip()
    git_dir = Path(git_dir_raw)
    if not git_dir.is_absolute():
        git_dir = root / git_dir
    return git_dir.resolve() / "lfs" / "objects" / oid[:2] / oid[2:4] / oid


def _purge_local_copy(root: Path, row: Mapping[str, Any]) -> None:
    target = root / str(row["clone_path"])
    target.unlink(missing_ok=True)
    _lfs_object_path(root, str(row["sha256"])).unlink(missing_ok=True)


def verify_batch(root: Path, batch: list[dict[str, Any]]) -> tuple[int, int]:
    if not batch:
        return 0, 0

    for row in batch:
        pointer_oid, pointer_size = pointer_for_path(root, str(row["clone_path"]))
        if pointer_oid != row["sha256"] or pointer_size != row["bytes"]:
            raise StreamingCloneError(
                f"LFS pointer identity mismatch: {row['clone_path']}"
            )
        _purge_local_copy(root, row)

    include = ",".join(str(row["clone_path"]) for row in batch)
    _run(
        ["git", "lfs", "fetch", "origin", "HEAD", f"--include={include}", "--exclude="],
        cwd=root,
        env={"GIT_LFS_SKIP_SMUDGE": "0"},
    )
    _run(
        ["git", "lfs", "checkout", *[str(row["clone_path"]) for row in batch]],
        cwd=root,
        env={"GIT_LFS_SKIP_SMUDGE": "0"},
    )

    verified_assets = 0
    verified_bytes = 0
    for row in batch:
        path = root / str(row["clone_path"])
        if not path.is_file():
            raise StreamingCloneError(
                f"LFS object did not materialize from origin: {row['clone_path']}"
            )
        size = path.stat().st_size
        if size != int(row["bytes"]):
            raise StreamingCloneError(
                f"LFS size mismatch after remote fetch: {row['clone_path']}"
            )
        sha = _sha256(path)
        if sha != str(row["sha256"]):
            raise StreamingCloneError(
                f"LFS SHA-256 mismatch after remote fetch: {row['clone_path']}"
            )
        verified_assets += 1
        verified_bytes += size
        _purge_local_copy(root, row)

    return verified_assets, verified_bytes


def verify_streaming(
    root: Path,
    *,
    shard_count: int,
    shard_index: int,
    batch_assets: int,
    batch_bytes: int,
) -> dict[str, Any]:
    manifest = load_manifest(root)
    rows = shard_rows(
        manifest["entries"],
        root=root,
        shard_count=shard_count,
        shard_index=shard_index,
    )
    batches = plan_batches(rows, max_assets=batch_assets, max_bytes=batch_bytes)

    verified_assets = 0
    verified_bytes = 0
    for batch_index, batch in enumerate(batches):
        assets, size = verify_batch(root, batch)
        verified_assets += assets
        verified_bytes += size
        print(
            json.dumps(
                {
                    "batch": batch_index,
                    "batch_assets": assets,
                    "batch_bytes": size,
                    "verified_assets": verified_assets,
                    "verified_bytes": verified_bytes,
                },
                sort_keys=True,
            ),
            flush=True,
        )

    expected_bytes = sum(int(row["bytes"]) for row in rows)
    complete = verified_assets == len(rows) and verified_bytes == expected_bytes
    return {
        "schema": "alina.streaming_fresh_clone_verification.v1",
        "complete": complete,
        "shard_count": shard_count,
        "shard_index": shard_index,
        "expected_assets": len(rows),
        "verified_assets": verified_assets,
        "expected_bytes": expected_bytes,
        "verified_bytes": verified_bytes,
        "batch_count": len(batches),
        "read_only": True,
        "real_execution": False,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", default=".")
    parser.add_argument("--shard-count", type=int, default=1)
    parser.add_argument("--shard-index", type=int, default=0)
    parser.add_argument("--batch-assets", type=int, default=DEFAULT_BATCH_ASSETS)
    parser.add_argument("--batch-bytes", type=int, default=DEFAULT_BATCH_BYTES)
    parser.add_argument("--output")
    parser.add_argument("--require-complete", action="store_true")
    args = parser.parse_args(argv)

    root = Path(args.root).resolve()
    try:
        report = verify_streaming(
            root,
            shard_count=args.shard_count,
            shard_index=args.shard_index,
            batch_assets=args.batch_assets,
            batch_bytes=args.batch_bytes,
        )
    except (StreamingCloneError, OSError, ValueError) as exc:
        print(f"ALINA_STREAMING_CLONE_FAIL: {exc}", file=sys.stderr)
        return 2

    rendered = json.dumps(report, indent=2, sort_keys=True)
    if args.output:
        Path(args.output).write_text(rendered + "\n", encoding="utf-8")
    print(rendered)
    if args.require_complete and not report["complete"]:
        return 3
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
