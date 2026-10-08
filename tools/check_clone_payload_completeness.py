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
import verify_materialized_clone as materializer

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


def git_pointers_for_paths(
    root: Path,
    paths: list[str],
) -> dict[str, tuple[str, int]]:
    """Read all current-tree LFS pointer blobs in one git process."""
    if not paths:
        return {}
    if any("\n" in path or "\r" in path for path in paths):
        raise CompletenessError("clone payload path contains a newline")

    request = "".join(f"HEAD:{path}\n" for path in paths).encode("utf-8")
    result = subprocess.run(
        ["git", "-C", str(root), "cat-file", "--batch"],
        input=request,
        capture_output=True,
        check=False,
    )
    if result.returncode != 0:
        detail = result.stderr.decode("utf-8", errors="replace").strip()
        raise CompletenessError(f"git cat-file --batch failed: {detail}")

    raw = memoryview(result.stdout)
    offset = 0
    pointers: dict[str, tuple[str, int]] = {}
    for path in paths:
        newline = result.stdout.find(b"\n", offset)
        if newline < 0:
            raise CompletenessError("truncated git cat-file batch header")
        header = bytes(raw[offset:newline]).decode("utf-8", errors="replace")
        offset = newline + 1
        parts = header.split()
        if len(parts) >= 2 and parts[-1] == "missing":
            raise CompletenessError(f"clone payload path is not tracked at HEAD: {path}")
        if len(parts) != 3 or parts[1] != "blob":
            raise CompletenessError(
                f"unexpected git cat-file header for {path}: {header}"
            )
        try:
            size = int(parts[2])
        except ValueError as exc:
            raise CompletenessError(
                f"invalid git blob size for {path}: {header}"
            ) from exc
        if size < 0 or offset + size > len(raw):
            raise CompletenessError(f"truncated git blob for {path}")
        blob = bytes(raw[offset : offset + size])
        offset += size
        if offset >= len(raw) or raw[offset] != 10:
            raise CompletenessError(f"missing git batch blob terminator for {path}")
        offset += 1
        pointers[path] = parse_lfs_pointer(blob)

    if offset != len(raw):
        trailing = bytes(raw[offset:]).strip()
        if trailing:
            raise CompletenessError("unexpected trailing data from git cat-file batch")
    return pointers


def git_pointer_for_path(root: Path, path: str) -> tuple[str, int]:
    return git_pointers_for_paths(root, [path])[path]

def git_tracked_payload_paths(root: Path) -> set[str]:
    """Prove that no extra LFS payload file is silently outside the manifest."""
    result = subprocess.run(
        ["git", "-C", str(root), "ls-tree", "-r", "-z", "--name-only", "HEAD", "--", "clone_payload/releases"],
        capture_output=True,
        check=False,
    )
    if result.returncode != 0:
        detail = result.stderr.decode("utf-8", errors="replace").strip()
        raise CompletenessError(f"git ls-tree failed: {detail}")
    return {os.fsdecode(path) for path in result.stdout.split(b"\0") if path}



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
    verify_worktree: bool = False,
) -> dict[str, Any]:
    manifest = mirror.load_manifest(root / MANIFEST_PATH)
    cloned = manifest_inventory(manifest)
    # An empty migration is conclusively INCOMPLETE for Alina, regardless of
    # transient GitHub API availability. Avoid many minutes of Release listing
    # retries and shared installation rate-limit consumption just to discover
    # that zero bytes have been mirrored. Source totals remain UNKNOWN, never 0.
    if not cloned:
        return {
            "schema": "alina.clone_payload_completeness.v1",
            "repository": repository,
            "complete": False,
            "reason": "MIRROR_NOT_STARTED",
            "source_inventory_checked": False,
            "source_assets": None,
            "clone_assets": 0,
            "source_bytes": None,
            "clone_bytes": 0,
            "missing_asset_count": None,
            "extra_asset_count": 0,
            "mismatch_count": 0,
            "missing_asset_ids_sample": [],
            "extra_asset_ids_sample": [],
            "mismatches_sample": [],
            "git_lfs_pointers_verified": False,
            "physical_worktree_verification_requested": bool(verify_worktree),
            "physical_worktree_mismatch_count": None,
            "physical_worktree_mismatches_sample": [],
            "read_only": True,
            "real_execution": False,
        }
    source = source_inventory(repository, token=token)

    source_ids = set(source)
    cloned_ids = set(cloned)
    missing_ids = sorted(source_ids - cloned_ids)
    extra_ids = sorted(cloned_ids - source_ids)
    mismatches: list[dict[str, Any]] = []
    common_ids = sorted(source_ids & cloned_ids)
    pointer_map: dict[str, tuple[str, int]] = {}
    if verify_git_pointers:
        pointer_paths = [
            str(cloned[asset_id].get("clone_path") or "")
            for asset_id in common_ids
        ]
        all_manifest_paths = [
            str(row.get("clone_path") or "") for row in cloned.values()
        ]
        if (
            len(set(all_manifest_paths)) != len(all_manifest_paths)
            or not all(path.startswith("clone_payload/releases/") for path in all_manifest_paths)
        ):
            mismatches.append({
                "asset_id": None,
                "kind": "invalid_or_duplicate_clone_path",
            })
        try:
            tracked = git_tracked_payload_paths(root)
            undeclared = sorted(tracked - set(all_manifest_paths))
            missing_tracked = sorted(set(all_manifest_paths) - tracked)
            if undeclared or missing_tracked:
                mismatches.append({
                    "asset_id": None,
                    "kind": "tracked_payload_set",
                    "undeclared_count": len(undeclared),
                    "missing_count": len(missing_tracked),
                    "undeclared_sample": undeclared[:15],
                    "missing_sample": missing_tracked[:15],
                })
            pointer_map = git_pointers_for_paths(root, pointer_paths)
        except CompletenessError as exc:
            mismatches.append({
                "asset_id": None,
                "kind": "git_tree_or_pointer",
                "error": str(exc),
            })
            pointer_map = {}

    for asset_id in common_ids:
        expected = source[asset_id]
        row = cloned[asset_id]
        expected_bytes = int(expected["bytes"])
        actual_bytes = int(row.get("bytes", -1))
        path = str(row.get("clone_path") or "")
        sha = str(row.get("sha256") or "").lower()

        if len(sha) != 64 or any(ch not in "0123456789abcdef" for ch in sha):
            mismatches.append({
                "asset_id": asset_id,
                "kind": "invalid_manifest_sha256",
            })
            continue
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
            pointer = pointer_map.get(path)
            if pointer is None:
                mismatches.append(
                    {
                        "asset_id": asset_id,
                        "kind": "git_pointer",
                        "error": f"pointer not available for {path}",
                    }
                )
                continue
            pointer_sha, pointer_size = pointer
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

    physical_report = materializer.verify(root) if verify_worktree else None
    physical_failures = (
        physical_report.get("failures_sample", [])
        if physical_report is not None
        else []
    )
    # A negative materialization verdict is fatal even when a report truncates
    # its failure examples to avoid generating enormous diagnostics.
    if physical_report is not None and not physical_report["complete"] and not physical_failures:
        physical_failures = [{"kind": "incomplete_physical_clone"}]
    source_bytes = sum(int(row["bytes"]) for row in source.values())
    cloned_bytes = sum(int(row.get("bytes") or 0) for row in cloned.values())
    complete = (
        not missing_ids
        and not extra_ids
        and not mismatches
        and not physical_failures
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
        "physical_worktree_verification_requested": bool(verify_worktree),
        "physical_worktree_mismatch_count": len(physical_failures),
        "physical_worktree_mismatches_sample": physical_failures[:50],
        "read_only": True,
        "real_execution": False,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repository", default=DEFAULT_REPOSITORY)
    parser.add_argument("--root", default=".")
    parser.add_argument("--require-complete", action="store_true")
    parser.add_argument("--skip-git-pointers", action="store_true")
    parser.add_argument(
        "--verify-worktree",
        action="store_true",
        help="stream every materialized LFS payload byte after a fresh clone",
    )
    parser.add_argument("--output")
    args = parser.parse_args(argv)

    if args.require_complete and args.skip_git_pointers:
        parser.error("--require-complete cannot skip Git LFS pointer verification")

    root = Path(args.root).resolve()
    token = os.getenv("GH_TOKEN") or os.getenv("GITHUB_TOKEN")
    try:
        report = audit(
            args.repository,
            root=root,
            token=token,
            verify_git_pointers=not args.skip_git_pointers,
            verify_worktree=args.verify_worktree,
        )
    except (CompletenessError, mirror.MirrorError, materializer.MaterializationError, OSError, ValueError) as exc:
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
