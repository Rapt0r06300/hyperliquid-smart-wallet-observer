#!/usr/bin/env python3
"""Fail-closed one-step local main update + all published Alina Release evidence.

This CLI only runs when explicitly invoked in a local checkout. It cannot wake
or depend on a user's PC from cloud GitHub Actions. No trading or uploads.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import subprocess
import sys

REPOSITORY = "Rapt0r06300/hyperliquid-smart-wallet-observer"
TRUSTED_ORIGINS = {
    f"https://github.com/{REPOSITORY}",
    f"https://github.com/{REPOSITORY}.git",
    f"git@github.com:{REPOSITORY}",
    f"git@github.com:{REPOSITORY}.git",
    f"ssh://git@github.com/{REPOSITORY}",
    f"ssh://git@github.com/{REPOSITORY}.git",
}


class SyncError(RuntimeError):
    """An update cannot be completed without risking locally owned files."""


def _git(root: Path, *args: str) -> str:
    try:
        done = subprocess.run(
            ["git", "-C", str(root), *args],
            check=False, capture_output=True, text=True,
        )
    except OSError as exc:
        raise SyncError("Git is required to synchronize Alina") from exc
    if done.returncode:
        detail = (done.stderr or done.stdout).strip()[:600]
        raise SyncError(f"git {args[0]} failed (exit {done.returncode}): {detail}")
    return done.stdout.strip()


def synchronize_main(root: Path, *, update: bool = True) -> str:
    """Fast-forward ONLY canonical main; never reset/rebase/stash local changes."""
    root = root.resolve()
    actual_root = Path(_git(root, "rev-parse", "--show-toplevel")).resolve()
    if actual_root != root:
        raise SyncError("execute from the canonical Alina repository root")
    branch = _git(root, "symbolic-ref", "--quiet", "--short", "HEAD")
    if branch != "main":
        raise SyncError(f"refusing update outside main (current: {branch})")
    origin = _git(root, "remote", "get-url", "origin")
    if origin not in TRUSTED_ORIGINS:
        raise SyncError("origin is not the single canonical Alina GitHub repository")
    if not update:
        return _git(root, "rev-parse", "HEAD")

    # This intentionally ignores untracked/ignored research files; Git itself
    # must refuse a merge that would overwrite any of those paths.
    if _git(root, "status", "--porcelain", "--untracked-files=no"):
        raise SyncError(
            "local tracked files were modified: commit or preserve them before "
            "sync; no reset, stash, forced checkout or overwritten files"
        )
    _git(root, "fetch", "--no-tags", "origin", "main")
    remote_sha = _git(root, "rev-parse", "refs/remotes/origin/main")
    # Non-fast-forward local history is an error, never hidden by an auto-rebase.
    _git(root, "merge", "--ff-only", "refs/remotes/origin/main")
    head = _git(root, "rev-parse", "HEAD")
    if head != remote_sha:
        raise SyncError("main is not identical to the fetched origin/main")
    return head


def restore_published(root: Path, *, preflight: bool = False,
                      snapshot: bool = True) -> int:
    """Delegate all byte-verification and SAFE gates to the ONE restore engine."""
    root = root.resolve()
    cmd = [
        sys.executable, "-u", str(root / "tools" / "restore_alina.py"),
        "--everything", "--recover-verifiable",
        "--destination", str(root / "runtime" / "recovery" / "full"),
        "--catalog", str(root / "catalog" / "DATA_INDEX.json"),
        "--metrics", str(root / "catalog" / "DATA_METRICS.json"),
    ]
    if preflight:
        cmd.append("--preflight-only")
    elif snapshot:
        # Missing optional snapshots are explicit NOT_PUBLISHED, not a false
        # 100% proof of unpublished bytes. Corrupt snapshots fail closed.
        cmd.extend(["--workspace", str(root), "--materialize-available-local-snapshot"])
    env = os.environ.copy()
    env["GIT_LFS_SKIP_SMUDGE"] = "1"
    env["PYTHONUTF8"] = "1"
    if not env.get("GH_TOKEN") and not env.get("GITHUB_TOKEN"):
        try:
            auth = subprocess.run(
                ["gh", "auth", "token"], check=False,
                capture_output=True, text=True,
            )
            if auth.returncode == 0 and auth.stdout.strip():
                env["GH_TOKEN"] = auth.stdout.strip()
        except OSError:
            pass
    try:
        return subprocess.run(cmd, cwd=root, env=env, check=False).returncode
    except OSError as exc:
        raise SyncError("Python restore could not be launched") from exc


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Update canonical main safely and hydrate every published "
                    "GitHub Release byte with SHA-256 verification."
    )
    parser.add_argument(
        "--skip-update", action="store_true",
        help="restore after a fresh git clone without another fetch",
    )
    parser.add_argument(
        "--preflight-only", action="store_true",
        help="inventory historical data and disk without downloading it",
    )
    parser.add_argument(
        "--no-snapshot-materialization", action="store_true",
        help="keep ignored workspace files intact; still download snapshot assets",
    )
    args = parser.parse_args(argv)
    if sys.version_info < (3, 10):
        print("ALINA_SYNC_FAIL: Python 3.10 or newer is required", file=sys.stderr)
        return 2
    root = Path(__file__).resolve().parents[1]
    try:
        head = synchronize_main(root, update=not args.skip_update)
        print(f"ALINA_MAIN_SHA={head}", flush=True)
        code = restore_published(
            root, preflight=args.preflight_only,
            snapshot=not args.no_snapshot_materialization,
        )
    except SyncError as exc:
        print(f"ALINA_SYNC_FAIL: {exc}", file=sys.stderr)
        return 2
    # Bind the local update and Release result to a durable, non-secret checkpoint.
    try:
        report_dir = root / "runtime" / "recovery" / "full"
        report_dir.mkdir(parents=True, exist_ok=True)
        checkpoint = {
            "schema": "alina.main_sync.v1",
            "repository": REPOSITORY,
            "branch": "main",
            "git_head": head,
            "restore_exit_code": code,
            "status": "RESTORE_EXIT_ZERO" if code == 0 else "RESTORE_INCOMPLETE",
            "restore_report": (
                "RESTORE_PREFLIGHT.json" if args.preflight_only else "RESTORE_REPORT.json"
            ),
        }
        path = report_dir / "SYNC_REPORT.json"
        temporary = path.with_suffix(".json.partial")
        temporary.write_text(json.dumps(checkpoint, indent=2, sort_keys=True) + "\n",
                             encoding="utf-8")
        temporary.replace(path)
    except OSError as exc:
        print(f"ALINA_SYNC_FAIL: cannot persist sync checkpoint: {exc}", file=sys.stderr)
        return 2
    if code:
        print(
            "ALINA_SYNC_INCOMPLETE: code is synchronized but published evidence "
            "is not proven byte-complete; see "
            "runtime/recovery/full/RESTORE_REPORT.json or RESTORE_PREFLIGHT.json",
            file=sys.stderr,
        )
    return code


if __name__ == "__main__":
    raise SystemExit(main())
