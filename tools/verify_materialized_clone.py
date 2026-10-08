#!/usr/bin/env python3
"""Verify that a fresh working tree contains real materialized clone payload bytes.

This is the post-clone acceptance test. It rejects Git LFS pointer placeholders,
missing files, wrong sizes and wrong SHA-256 values.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from collections.abc import Mapping
from pathlib import Path

MANIFEST_PATH = Path("clone_payload/MANIFEST.json")
LFS_POINTER_PREFIX = b"version https://git-lfs.github.com/spec/v1\n"


class MaterializationError(RuntimeError):
    pass


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(8 * 1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def verify(root: Path) -> dict:
    manifest_path = root / MANIFEST_PATH
    if not manifest_path.is_file():
        raise MaterializationError(f"missing manifest: {manifest_path}")
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise MaterializationError("invalid clone payload manifest JSON") from exc
    if not isinstance(manifest, Mapping):
        raise MaterializationError("clone payload manifest is not an object")
    if manifest.get("schema") != "alina.clone_payload_manifest.v1":
        raise MaterializationError("unsupported clone payload manifest schema")
    rows = manifest.get("entries")
    if not isinstance(rows, list):
        raise MaterializationError("clone payload entries are missing")

    failures: list[dict] = []
    verified_assets = 0
    verified_bytes = 0
    seen_paths: set[str] = set()

    for row in rows:
        if not isinstance(row, Mapping):
            failures.append({"kind": "invalid_manifest_row"})
            continue
        relative = str(row.get("clone_path") or "")
        expected_size = int(row.get("bytes", -1))
        expected_sha = str(row.get("sha256") or "").lower()
        relative_path = Path(relative)
        if (
            not relative
            or relative_path.is_absolute()
            or relative_path.parts[:2] != ("clone_payload", "releases")
            or ".." in relative_path.parts
            or expected_size < 0
            or len(expected_sha) != 64
            or any(ch not in "0123456789abcdef" for ch in expected_sha)
        ):
            failures.append(
                {"kind": "invalid_identity", "asset_id": row.get("asset_id")}
            )
            continue
        if relative in seen_paths:
            failures.append({"kind": "duplicate_path", "path": relative})
            continue
        seen_paths.add(relative)

        untrusted = root / relative_path
        path = untrusted.resolve()
        root_resolved = root.resolve()
        allowed_root = root_resolved / "clone_payload" / "releases"
        if (
            untrusted.is_symlink()
            or path == allowed_root
            or allowed_root not in path.parents
        ):
            failures.append({"kind": "path_escape", "path": relative})
            continue
        if not path.is_file():
            failures.append({"kind": "missing", "path": relative})
            continue
        actual_size = path.stat().st_size
        if actual_size <= 200:
            prefix = path.read_bytes()[: len(LFS_POINTER_PREFIX)]
            if prefix == LFS_POINTER_PREFIX:
                failures.append({"kind": "lfs_pointer_not_materialized", "path": relative})
                continue
        if actual_size != expected_size:
            failures.append(
                {
                    "kind": "size",
                    "path": relative,
                    "expected": expected_size,
                    "actual": actual_size,
                }
            )
            continue
        actual_sha = _sha256(path)
        if actual_sha != expected_sha:
            failures.append(
                {
                    "kind": "sha256",
                    "path": relative,
                    "expected": expected_sha,
                    "actual": actual_sha,
                }
            )
            continue
        verified_assets += 1
        verified_bytes += actual_size

    manifest_assets = int(manifest.get("total_assets") or 0)
    manifest_bytes = int(manifest.get("total_bytes") or 0)
    # An empty mirror can be internally consistent but is never an acceptable
    # proof that historical Alina Releases have been cloned.
    complete = (
        manifest_assets > 0
        and not failures
        and verified_assets == len(rows) == manifest_assets
        and verified_bytes == manifest_bytes
    )
    return {
        "schema": "alina.materialized_clone_verification.v1",
        "complete": complete,
        "manifest_assets": manifest_assets,
        "verified_assets": verified_assets,
        "manifest_bytes": manifest_bytes,
        "verified_bytes": verified_bytes,
        "failure_count": len(failures),
        "failures_sample": failures[:50],
        "real_execution": False,
        "read_only": True,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", default=".")
    parser.add_argument("--require-complete", action="store_true")
    parser.add_argument("--output")
    args = parser.parse_args(argv)

    try:
        report = verify(Path(args.root).resolve())
    except (MaterializationError, OSError, ValueError) as exc:
        print(f"ALINA_MATERIALIZED_CLONE_FAIL: {exc}", file=sys.stderr)
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
