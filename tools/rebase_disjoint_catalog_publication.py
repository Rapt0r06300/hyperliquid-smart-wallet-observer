#!/usr/bin/env python3
"""Rebase a catalog writer only across unrelated, immutable campaign checkpoints.

Never rebase across edits to the Dataset index, manifests, metrics, validation
code, control plane, or any unknown path. A caller must have fetched origin/main
and must still publish with a normal non-force push.
"""
from __future__ import annotations

import argparse
import subprocess
import sys

ALLOWED_PREFIXES = (
    "catalog/campaigns/",
    "catalog/receipts/",
    "catalog/campaign-history/",
)


def only_campaign_checkpoints(paths: list[str]) -> bool:
    return all(
        path and any(path.startswith(prefix) for prefix in ALLOWED_PREFIXES)
        for path in paths
    )


def git(*args: str, check: bool = True) -> subprocess.CompletedProcess[bytes]:
    return subprocess.run(["git", *args], capture_output=True, check=check)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--remote", default="origin/main")
    args = parser.parse_args()
    try:
        if git("status", "--porcelain").stdout.strip():
            raise ValueError("uncommitted workspace changes; rebase refused")
        # Exactly one freshly produced publication commit is eligible.
        parent = git("rev-parse", "HEAD^").stdout.decode().strip()
        ancestry = git("merge-base", "--is-ancestor", parent, args.remote, check=False)
        if ancestry.returncode:
            raise ValueError("publication parent is not an ancestor of remote HEAD")
        changed = git("diff", "--name-only", "-z", parent, args.remote).stdout
        paths = [part.decode("utf-8") for part in changed.split(b"\0") if part]
        if not only_campaign_checkpoints(paths):
            sample = paths[:10]
            raise ValueError(f"remote changed source/control files: {sample}")
        rebased = git("rebase", args.remote, check=False)
        if rebased.returncode:
            git("rebase", "--abort", check=False)
            raise ValueError("rebase conflict; rebuild publication from main")
        print(f"SAFE_DISJOINT_REBASE_OK campaign_paths={len(paths)}")
        return 0
    except (OSError, UnicodeError, ValueError, subprocess.CalledProcessError) as exc:
        print(f"SAFE_DISJOINT_REBASE_REFUSED: {exc}", file=sys.stderr)
        return 3


if __name__ == "__main__":
    raise SystemExit(main())
