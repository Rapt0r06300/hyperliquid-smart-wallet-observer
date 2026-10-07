#!/usr/bin/env python3
"""Prove byte-identity coverage between GitHub Release assets and clone_payload LFS.

"Same number of bytes" is defined here as application payload parity:
every explicit GitHub Release asset has exactly one current-tree clone payload
entry with the same immutable asset id, byte size and SHA-256/LFS OID.

Git server packfiles are intentionally not compared: Git may compress/repack the
same object graph differently on server and client.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import mirror_releases_to_clone_lfs as mirror

DEFAULT_REPOSITORY = mirror.DEFAULT_REPOSITORY
MANIFEST_PATH = mirror.MANIFEST_PATH
LFS_POINTER_RE = re.compile(
    rb"\Aversion https://git-lfs.github.com/spec/v1\n"
    rb"oid sha256:([0-9a-f]{64})\n"
    rb"size ([0-9]+)\n?\Z"
)


class CompletenessError(RuntimeError):
    pass


def parse_lfs_pointer(raw: bytes) -> tuple[str, int]:
    match = LFS_POINTER_RE.match(raw)
    if not match:
        raise CompletenessError("invalid Git LFS pointer")
    return match.group(1).decode("ascii"), int(match.group(2))


def git_pointer_for_path(root: Path, path: str) -> tuple[str, int]:
    result = subprocess.run(
        ["git", "-C", str(root), "show", f"HEAD:{path}"],
        capture_output=True,
        check=False,
    )
    if result.returncode != 0:
        raise CompletenessError(f"clone payload path is not tracked at HEAD: {path}")
    return parse_lfs_pointer(result.stdout)


def source_inventory(
    repository: str,
    *,
    token: str | None,
) -> dict[int, dict[str, Any]]:
    inventory: dict[int, dict[str, Any]] = {}
    for release in mirror.iter_releases_oldest_first(repository, token=token):
        assets = release.get("assets")
        if not isinstance(assets, list):
            continue
        for asset in assets:
            if not isinstance(asset, Mapping):
                continue
            asset_id = int(asset.get("id") or 0)
            if asset_id <= 0:
                raise CompletenessError("GitHub Release asset without immutable id")
            if asset_id in inventory:
                raise CompletenessError(f"duplicate GitHub asset id: {asset_id}")
            inventory[asset_id] = {
                "release_id": int(release.get("id") or 0),
                "release_tag": str(release.get("tag_name") or ""),
                "asset_name": str(asset.get("name") or ""),
                "bytes": int(asset.get("size") or 0),
                "source_digest": str(asset.get("digest") or ""),
            }
    return inventory


def manifest_inventory(manifest: Mapping[str, Any]) -> dict[int, Mapping[str, Any]]:
    inventory: dict[int, Mapping[str, Any]] = {}
    rows = manifest.get("entries")
    if not isinstance(rows, list):
        raise CompletenessError("clone manifest entries missing")
    for row in rows:
        if not isinstance(row, Mapping):
            raise CompletenessError("invalid clone manifest row")
        asset_id = int(row.get("asset_id") or 0)
        if asset_id <= 0:
            raise CompletenessError("clone manifest row has invalid asset id")
        if asset_id in inventory:
            raise CompletenessError(f"duplicate clone manifest asset id: {asset_id}")
        inventory[asset_id] = row
    return inventory


def audit(
    repository: str,
    *,
    root: Path,
    token: str | None,
    verify_git_pointers: bool,
) -> dict[str, Any]:
    manifest = mirror.load_manifest(root / MANIFEST_PATH)
    source = source_inventory(repository, token=token)
    cloned = manifest_inventory(manifest)

    source_ids = set(source)
    cloned_ids = set(cloned)
    missing_ids = sorted(source_ids - cloned_ids)
    extra_ids = sorted(cloned_ids - source_ids)
    mismatches: list[dict[str, Any]] = []

    for asset_id in sorted(source_ids & cloned_ids):
        expected = source[asset_id]
        row = cloned[asset_id]
        expected_bytes = int(expected["bytes"])
        actual_bytes = int(row.get("bytes") or -1)
        path = str(row.get("clone_path") or "")
        sha = str(row.get("sha256") or "").lower()

        if expected_bytes != actual_bytes:
            mismatches.append(
                {
                    "asset_id": asset_id,
                    "kind": "size",
                    "source": expected_bytes,
                    "clone": actual_bytes,
                }
            )
            continue
        source_digest = str(expected.get("source_digest") or "")
        if source_digest.lower().startswith("sha256:"):
            expected_sha = source_digest.split(":", 1)[1].lower()
            if sha != expected_sha:
                mismatches.append(
                    {
                        "asset_id": asset_id,
                        "kind": "sha256",
                        "source": expected_sha,
                        "clone": sha,
                    }
                )
                continue
        if verify_git_pointers:
            try:
                pointer_sha, pointer_size = git_pointer_for_path(root, path)
            except CompletenessError as exc:
                mismatches.append(
                    {
                        "asset_id": asset_id,
                        "kind": "git_pointer",
                        "error": str(exc),
                    }
                )
                continue
            if pointer_sha != sha or pointer_size != actual_bytes:
                mismatches.append(
                    {
                        "asset_id": asset_id,
                        "kind": "git_lfs_identity",
                        "manifest_sha256": sha,
                        "pointer_sha256": pointer_sha,
                        "manifest_bytes": actual_bytes,
                        "pointer_bytes": pointer_size,
                    }
                )

    source_bytes = sum(int(row["bytes"]) for row in source.values())
    cloned_bytes = sum(int(row.get("bytes") or 0) for row in cloned.values())
    complete = (
        not missing_ids
        and not extra_ids
        and not mismatches
        and source_bytes == cloned_bytes
    )
    return {
        "schema": "alina.clone_payload_completeness.v1",
        "repository": repository,
        "complete": complete,
        "source_assets": len(source),
        "clone_assets": len(cloned),
        "source_bytes": source_bytes,
        "clone_bytes": cloned_bytes,
        "missing_asset_count": len(missing_ids),
        "extra_asset_count": len(extra_ids),
        "mismatch_count": len(mismatches),
        "missing_asset_ids_sample": missing_ids[:50],
        "extra_asset_ids_sample": extra_ids[:50],
        "mismatches_sample": mismatches[:50],
        "git_lfs_pointers_verified": bool(verify_git_pointers),
        "read_only": True,
        "real_execution": False,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repository", default=DEFAULT_REPOSITORY)
    parser.add_argument("--root", default=".")
    parser.add_argument("--require-complete", action="store_true")
    parser.add_argument("--skip-git-pointers", action="store_true")
    parser.add_argument("--output")
    args = parser.parse_args(argv)

    root = Path(args.root).resolve()
    token = os.getenv("GH_TOKEN") or os.getenv("GITHUB_TOKEN")
    try:
        report = audit(
            args.repository,
            root=root,
            token=token,
            verify_git_pointers=not args.skip_git_pointers,
        )
    except (CompletenessError, mirror.MirrorError, OSError, ValueError) as exc:
        print(f"ALINA_CLONE_COMPLETENESS_FAIL: {exc}", file=sys.stderr)
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
