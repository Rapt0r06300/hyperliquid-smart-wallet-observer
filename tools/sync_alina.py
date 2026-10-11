#!/usr/bin/env python3
"""Update canonical main and restore all verifiable same-repository Release data.

Operator-initiated only; never runs on a GitHub worker or starts a collector.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REPOSITORY = "Rapt0r06300/hyperliquid-smart-wallet-observer"
ALLOWED_FLAGS = {
    "--preflight-only", "--recover-verifiable",
    "--materialize-local-snapshot", "--materialize-available-local-snapshot",
}


class SyncError(RuntimeError):
    pass


def _git(*args: str) -> str:
    try:
        result = subprocess.run(
            ["git", *args], cwd=ROOT, capture_output=True, text=True,
            encoding="utf-8", errors="replace", check=False,
            env={**os.environ, "GIT_LFS_SKIP_SMUDGE": "1"},
        )
    except OSError as exc:
        raise SyncError(f"Git is not available: {exc}") from exc
    if result.returncode:
        # Avoid logging remote credentials, environment or private paths.
        raise SyncError(f"Git command failed: {args[0]} (exit {result.returncode})")
    return result.stdout.strip()


def _canonical_origin(url: str) -> bool:
    url = url.strip().rstrip("/")
    if url.lower().endswith(".git"):
        url = url[:-4]
    return url.casefold() in {
        f"https://github.com/{REPOSITORY}".casefold(),
        f"git@github.com:{REPOSITORY}".casefold(),
        f"ssh://git@github.com/{REPOSITORY}".casefold(),
    }


def sync_main() -> tuple[str, str]:
    if not _canonical_origin(_git("remote", "get-url", "origin")):
        raise SyncError("origin must point to the single canonical GitHub repository")
    if _git("symbolic-ref", "--quiet", "--short", "HEAD") != "main":
        raise SyncError("checkout is not on the canonical main branch")
    if _git("status", "--porcelain", "--untracked-files=no"):
        raise SyncError("tracked local changes found; refusing to overwrite them")
    previous = _git("rev-parse", "HEAD")
    _git("fetch", "--no-tags", "origin", "main")
    # No reset, force, rebase or implicit merge commit.
    _git("merge", "--ff-only", "FETCH_HEAD")
    current = _git("rev-parse", "HEAD")
    if _git("status", "--porcelain", "--untracked-files=no"):
        raise SyncError("checkout became dirty after fast-forward")
    return previous, current


def main(argv: list[str] | None = None) -> int:
    requested = list(sys.argv[1:] if argv is None else argv)
    if any(flag not in ALLOWED_FLAGS for flag in requested):
        print("ALINA_SYNC_FAIL: unsupported option; allowed: " +
              ", ".join(sorted(ALLOWED_FLAGS)), file=sys.stderr)
        return 2
    if ("--materialize-local-snapshot" in requested and
            "--materialize-available-local-snapshot" in requested):
        print("ALINA_SYNC_FAIL: conflicting snapshot options", file=sys.stderr)
        return 2
    try:
        before, after = sync_main()
    except SyncError as exc:
        print(f"ALINA_SYNC_FAIL: {exc}", file=sys.stderr)
        return 2

    flags = list(requested)
    if "--recover-verifiable" not in flags:
        flags.insert(0, "--recover-verifiable")
    if ("--preflight-only" not in flags and
            "--materialize-local-snapshot" not in flags and
            "--materialize-available-local-snapshot" not in flags):
        flags.append("--materialize-available-local-snapshot")
    command = [sys.executable, "tools/restore_alina.py", "--everything",
               "--repository", REPOSITORY, "--clone-root", ".",
               "--workspace", ".", "--destination", "runtime/recovery/full",
               *flags]
    env = {**os.environ, "GIT_LFS_SKIP_SMUDGE": "1"}
    if not env.get("GH_TOKEN") and not env.get("GITHUB_TOKEN"):
        # Prefer an existing GitHub CLI login; never print the token.
        try:
            auth = subprocess.run(
                ["gh", "auth", "token"], capture_output=True, text=True,
                timeout=15, check=False,
            )
            if auth.returncode == 0 and auth.stdout.strip():
                env["GH_TOKEN"] = auth.stdout.strip()
        except (OSError, subprocess.TimeoutExpired):
            pass
    try:
        result = subprocess.run(command, cwd=ROOT, env=env, check=False)
        code = result.returncode
    except OSError as exc:
        print(f"ALINA_SYNC_FAIL: Python restore could not start: {exc}", file=sys.stderr)
        code = 2

    # Persist a lightweight and non-secret local checkpoint, also on failure.
    try:
        report_dir = ROOT / "runtime" / "recovery" / "full"
        report_dir.mkdir(parents=True, exist_ok=True)
        checkpoint = {
            "schema": "alina.main_sync.v1",
            "repository": REPOSITORY,
            "branch": "main",
            "head_before": before,
            "head_after": after,
            "restore_exit_code": code,
            "restore_report": "runtime/recovery/full/RESTORE_REPORT.json",
            "status": "RESTORE_EXIT_ZERO" if code == 0 else "RESTORE_INCOMPLETE",
        }
        path = report_dir / "SYNC_REPORT.json"
        temp = path.with_suffix(".json.partial")
        temp.write_text(json.dumps(checkpoint, indent=2, sort_keys=True) + "\n",
                        encoding="utf-8")
        temp.replace(path)
    except OSError as exc:
        print(f"ALINA_SYNC_FAIL: cannot persist sync checkpoint: {exc}", file=sys.stderr)
        return 2
    print(f"ALINA_SYNC: main {before} -> {after}; restore exit {code}")
    return code


if __name__ == "__main__":
    raise SystemExit(main())
